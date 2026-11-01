/*
 * LPRNet 纯整数软件推理（AE350 / 任意无 OS 环境可用，C99）。
 *
 * 与 sw_ref.py 逐位等价：
 *   conv:  int32 累加(int8 权重 × uint8 激活) + int32 bias → ×mult → clamp[0,255]
 *   pool:  窗口取最大(uint8，scale 不变)
 *   fc:    int32 累加 + bias → argmax
 *
 * 内存：本文件不动态分配；调用方提供两个工作缓冲 work0/work1，
 *       每个需 >= 最大激活量 = 32*32*128 = 131072 字节（uint8）。
 *       在 AE350 上把它们指向 DDR3；在 PC 上可 malloc(131072)。
 */
#include <stdint.h>
#include <stddef.h>
#include "lprnet_sw.h"

static const uint8_t *g_bin = 0;

void lprnet_sw_init(const uint8_t *bin, uint32_t bin_size)
{
    (void)bin_size;
    g_bin = bin;
}

static const int8_t *W(const lprnet_layer_t *L)
{
    return (const int8_t *)(g_bin + L->w_offset);
}

static const int32_t *B(const lprnet_layer_t *L)
{
    return (const int32_t *)(g_bin + L->b_offset);
}

/* conv：in 为 (in_ch, ih, iw) 通道优先；out 为 (out_ch, ih, iw)。stride=1、pad 由层参数给定 */
static void conv_layer(const lprnet_layer_t *L, const uint8_t *in, int ih, int iw, uint8_t *out)
{
    const int8_t *w = W(L);
    const int32_t *b = B(L);
    const int cin = L->in_ch, cout = L->out_ch, kh = L->kh, kw = L->kw, pad = L->pad;
    const float mult = L->w_scale * L->a_scale / L->out_scale;
    int oc, oy, ox, ic, ky, kx;

    for (oc = 0; oc < cout; ++oc) {
        for (oy = 0; oy < ih; ++oy) {
            for (ox = 0; ox < iw; ++ox) {
                int32_t acc = b[oc];
                for (ic = 0; ic < cin; ++ic) {
                    const uint8_t *ip = in + ((size_t)ic * ih + oy) * iw + ox;
                    const int8_t *wp = w + (((size_t)oc * cin + ic) * kh) * kw;
                    for (ky = 0; ky < kh; ++ky) {
                        int iy = oy + ky - pad;
                        if (iy < 0 || iy >= ih) { wp += kw; continue; }
                        for (kx = 0; kx < kw; ++kx) {
                            int ix = ox + kx - pad;
                            if (ix < 0 || ix >= iw) { ++wp; continue; }
                            acc += (int32_t)(*wp++) * (int32_t)ip[(size_t)(iy - oy) * iw + (ix - ox)];
                        }
                    }
                }
                float q = (float)acc * mult;
                if (q < 0.0f) q = 0.0f; else if (q > 255.0f) q = 255.0f;
                out[((size_t)oc * ih + oy) * iw + ox] = (uint8_t)(q + 0.5f);
            }
        }
    }
}

/* pool：窗口 kh×kw，步长 stride_h×stride_w，输出 (c, ih/sh, iw/sw) */
static void pool_layer(const lprnet_layer_t *L, const uint8_t *in, int c, int ih, int iw, uint8_t *out)
{
    const int kh = L->kh, kw = L->kw, sh = L->stride_h, sw = L->stride_w;
    const int oh = ih / sh, ow = iw / sw;
    int cc, oy, ox, ky, kx;

    for (cc = 0; cc < c; ++cc) {
        for (oy = 0; oy < oh; ++oy) {
            for (ox = 0; ox < ow; ++ox) {
                uint8_t m = 0;
                for (ky = 0; ky < kh; ++ky) {
                    for (kx = 0; kx < kw; ++kx) {
                        uint8_t v = in[((size_t)cc * ih + (oy * sh + ky)) * iw + (ox * sw + kx)];
                        if (v > m) m = v;
                    }
                }
                out[((size_t)cc * oh + oy) * ow + ox] = m;
            }
        }
    }
}

/* fc：in 为扁平 in_features 个 uint8；out 为 out_features 个 int32 */
static void fc_layer(const lprnet_layer_t *L, const uint8_t *in, int32_t *out)
{
    const int8_t *w = W(L);
    const int32_t *b = B(L);
    const int n = L->in_ch, m = L->out_ch;
    int o, i;

    for (o = 0; o < m; ++o) {
        int32_t acc = b[o];
        const int8_t *wp = w + (size_t)o * n;
        for (i = 0; i < n; ++i)
            acc += (int32_t)wp[i] * (int32_t)in[i];
        out[o] = acc;
    }
}

void lprnet_sw_infer(const uint8_t *img32x128, uint8_t out_cls[7], int32_t *out_scores,
                     uint8_t *work0, uint8_t *work1)
{
    int c = 1, h = LPRNET_IN_H, w = LPRNET_IN_W;
    const uint8_t *src = img32x128;
    uint8_t *buf[2] = { work0, work1 };
    int cur = 0;
    int i;

    for (i = 0; i < LPRNET_NUM_LAYERS; ++i) {
        const lprnet_layer_t *L = &LPRNET_LAYERS[i];
        if (L->type == 0) {                    /* conv */
            conv_layer(L, src, h, w, buf[cur]);
            c = L->out_ch;
        } else if (L->type == 1) {             /* pool */
            pool_layer(L, src, c, h, w, buf[cur]);
            h /= L->stride_h;
            w /= L->stride_w;
        } else {                               /* fc */
            fc_layer(L, src, out_scores);
            break;
        }
        src = buf[cur];
        cur ^= 1;
    }

    /* 每个时间步在 39 类里取 argmax */
    for (i = 0; i < LPRNET_TIMESTEPS; ++i) {
        int k, best = 0;
        int32_t bv = out_scores[i * LPRNET_CLASSES];
        for (k = 1; k < LPRNET_CLASSES; ++k) {
            int32_t v = out_scores[i * LPRNET_CLASSES + k];
            if (v > bv) { bv = v; best = k; }
        }
        out_cls[i] = (uint8_t)best;
    }
}
