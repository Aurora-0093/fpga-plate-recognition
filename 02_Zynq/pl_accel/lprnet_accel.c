/*
 * FPGA 卷积加速器驱动（Zynq-7020）—— 256KB BRAM 分块版
 *
 * 为什么分块：
 *   512KB BRAM 占 7020 的 81%（114/140 个 BRAM36），Vivado 布局/时序优化会卡死。
 *   砍到 256KB（41%）后，把每层卷积按输出通道分成若干块依次跑。
 *
 * 每次运行的约束：
 *   权重区  ≤ 147456 B (0x24000)
 *   输入区  ≤ 32KB
 *   输出区  ≤ 64KB  (16384 个 int32)
 *
 * BRAM 布局（256KB = 0x40000）：
 *   0x000000  控制字（9 个字）
 *   0x000100  权重区（当前块的打包权重，最大 147456 B）→ 0x024100
 *   0x025000  输入区（最大 32KB）→ 0x02D000
 *   0x02E000  输出区 int32（最大 64KB）→ 0x03E000
 *
 * 每层分块数：
 *   conv2 (32→64, 16x64)   输出 256KB → 4 块（每块 16 通道）
 *   conv3 (64→128, 8x32)   输出 128KB → 2 块（每块 64 通道）
 *   conv4 (128→256, 4x32)  输出 128KB → 2 块（每块 128 通道）
 */
#include <stdint.h>
#include "xparameters.h"
#include "xil_io.h"
#include "lprnet_sw.h"
#include "lprnet_accel.h"

#ifndef XPAR_AXI_BRAM_CTRL_0_S_AXI_BASEADDR
#define XPAR_AXI_BRAM_CTRL_0_S_AXI_BASEADDR 0x40000000u
#endif
#define BRAM_BASE XPAR_AXI_BRAM_CTRL_0_S_AXI_BASEADDR

/* 区域字节偏移（256KB 布局） */
#define W_OFF    0x000100u     /* 权重区（每块重排后写入） */
#define IN_OFF   0x025000u     /* 输入区 */
#define OUT_OFF  0x02E000u     /* 输出区 int32 */
#define W_MAX    (0x025000u - W_OFF)     /* 权重区容量 = 147456 B */
#define OUT_MAX  16384u                  /* 输出区容量（int32 个数）= 64KB */

/* 控制字字节偏移 */
#define CTRL    0x00u
#define CIN     0x04u
#define COUT    0x08u
#define HIN     0x0Cu
#define WIN     0x10u
#define WGT     0x14u
#define INP     0x18u
#define OUTP    0x1Cu
#define CYC     0x20u

static const uint8_t *g_bin = 0;

extern const unsigned char lprnet_weights[];

static inline void bram_w(uint32_t off, uint32_t v) { Xil_Out32(BRAM_BASE + off, v); }
static inline uint32_t bram_r(uint32_t off) { return Xil_In32(BRAM_BASE + off); }

static inline const int8_t *W(const lprnet_layer_t *L) { return (const int8_t *)(g_bin + L->w_offset); }
static inline const int32_t *B(const lprnet_layer_t *L) { return (const int32_t *)(g_bin + L->b_offset); }

/* 把 [oc_start, oc_start+oc_cnt) 的权重打包写进 BRAM（16 通道一块） */
static void repack_chunk(const lprnet_layer_t *L, uint32_t bram_off, int oc_start, int oc_cnt)
{
    const int8_t *w = W(L);
    int cin = L->in_ch;
    int ocb, ic, kh, kw, g, lane;

    for (ocb = 0; ocb < oc_cnt / 16; ++ocb) {
        for (ic = 0; ic < cin; ++ic) {
            for (kh = 0; kh < 3; ++kh) {
                for (kw = 0; kw < 3; ++kw) {
                    uint32_t gbyte = bram_off +
                        (uint32_t)(((ocb * cin + ic) * 9 + kh * 3 + kw) << 4);
                    for (g = 0; g < 4; ++g) {
                        uint32_t val = 0;
                        for (lane = 0; lane < 4; ++lane) {
                            int oc = oc_start + ocb * 16 + g * 4 + lane;
                            int8_t v = w[(size_t)oc * cin * 9 + ic * 9 + kh * 3 + kw];
                            val |= ((uint32_t)(uint8_t)v) << (lane * 8);
                        }
                        bram_w(gbyte + (uint32_t)g * 4, val);
                    }
                }
            }
        }
    }
}

void lprnet_accel_init(void)
{
    g_bin = lprnet_weights;
    bram_w(CTRL, 0);
}

/* 启动一次卷积（输出块从 ocb0 开始，共 cout 个输出通道） */
static void accel_run(uint16_t cin, uint16_t cout, uint16_t h, uint16_t w,
                      uint32_t woff, uint32_t inoff, uint32_t outoff)
{
    bram_w(CTRL, 0);
    bram_w(CIN, cin);
    bram_w(COUT, cout);
    bram_w(HIN, h);
    bram_w(WIN, w);
    bram_w(WGT, woff);
    bram_w(INP, inoff);
    bram_w(OUTP, outoff);
    bram_w(CTRL, 1);
    while (!(bram_r(CTRL) & 0x4)) { }
}

/* 输入特征图（uint8，ic 主序）写进 BRAM */
static void write_input(const uint8_t *in, uint32_t nbytes, uint32_t inoff)
{
    uint32_t i;
    for (i = 0; i < nbytes; i += 4) {
        uint32_t val = 0;
        uint32_t j;
        for (j = 0; j < 4; ++j) {
            uint32_t b8 = (i + j < nbytes) ? in[i + j] : 0;
            val |= b8 << (j * 8);
        }
        bram_w(inoff + i, val);
    }
}

/* 读 int32 输出 + bias + requant + clamp -> uint8（bias 从 oc0 开始） */
static void read_requant(const lprnet_layer_t *L, uint8_t *out,
                         int oc_cnt, int n, int oc0)
{
    const int32_t *b = B(L);
    float mult = L->w_scale * L->a_scale / L->out_scale;
    int i;
    for (i = 0; i < oc_cnt * n; ++i) {
        int oc = i / n;
        int32_t acc = (int32_t)bram_r(OUT_OFF + (uint32_t)i * 4) + b[oc0 + oc];
        float q = (float)acc * mult;
        if (q < 0.0f) q = 0.0f; else if (q > 255.0f) q = 255.0f;
        out[i] = (uint8_t)(q + 0.5f);
    }
}

/* 用 FPGA 跑整层卷积（自动按输出通道分块） */
static void accel_conv(const lprnet_layer_t *L, const uint8_t *in, int h, int w, uint8_t *out)
{
    int cin = L->in_ch, cout = L->out_ch;
    int n = h * w;
    int by_out = (int)(OUT_MAX / (uint32_t)n);          /* 输出区限制 */
    int by_wgt = (int)(W_MAX / (uint32_t)(cin * 9));    /* 权重区限制 */
    int chunk = (by_out < by_wgt) ? by_out : by_wgt;
    int oc;

    chunk = (chunk / 16) * 16;          /* 必须是 16 的倍数 */
    if (chunk < 16) chunk = 16;
    if (chunk > cout) chunk = cout;

    write_input(in, (uint32_t)cin * (uint32_t)n, IN_OFF);

    for (oc = 0; oc < cout; oc += chunk) {
        int cnt = (oc + chunk <= cout) ? chunk : (cout - oc);
        repack_chunk(L, W_OFF, oc, cnt);
        accel_run((uint16_t)cin, (uint16_t)cnt, (uint16_t)h, (uint16_t)w,
                  W_OFF, IN_OFF, OUT_OFF);
        read_requant(L, out + (size_t)oc * n, cnt, n, oc);
    }
}

/* ---- 软件层（conv1 / pool / fc），与 lprnet_sw.c 一致 ---- */
static void conv1_sw(const lprnet_layer_t *L, const uint8_t *in, int ih, int iw, uint8_t *out)
{
    const int8_t *w = W(L);
    const int32_t *b = B(L);
    const float mult = L->w_scale * L->a_scale / L->out_scale;
    int oc, oy, ox, ic, ky, kx;
    for (oc = 0; oc < L->out_ch; ++oc)
        for (oy = 0; oy < ih; ++oy)
            for (ox = 0; ox < iw; ++ox) {
                int32_t acc = b[oc];
                for (ic = 0; ic < L->in_ch; ++ic) {
                    const uint8_t *ip = in + ((size_t)ic * ih + oy) * iw + ox;
                    const int8_t *wp = w + (((size_t)oc * L->in_ch + ic) * 3) * 3;
                    for (ky = 0; ky < 3; ++ky) {
                        int iy = oy + ky - 1;
                        if (iy < 0 || iy >= ih) { wp += 3; continue; }
                        for (kx = 0; kx < 3; ++kx) {
                            int ix = ox + kx - 1;
                            if (ix < 0 || ix >= iw) { ++wp; continue; }
                            acc += (int32_t)(*wp++) * (int32_t)ip[(size_t)(iy - oy) * iw + (ix - ox)];
                        }
                    }
                }
                {
                    float q = (float)acc * mult;
                    if (q < 0.0f) q = 0.0f; else if (q > 255.0f) q = 255.0f;
                    out[((size_t)oc * ih + oy) * iw + ox] = (uint8_t)(q + 0.5f);
                }
            }
}

static void pool_sw(const lprnet_layer_t *L, const uint8_t *in, int c, int ih, int iw, uint8_t *out)
{
    int kh = L->kh, kw = L->kw, sh = L->stride_h, sw = L->stride_w;
    int oh = ih / sh, ow = iw / sw;
    int cc, oy, ox, ky, kx;
    for (cc = 0; cc < c; ++cc)
        for (oy = 0; oy < oh; ++oy)
            for (ox = 0; ox < ow; ++ox) {
                uint8_t m = 0;
                for (ky = 0; ky < kh; ++ky)
                    for (kx = 0; kx < kw; ++kx) {
                        uint8_t v = in[((size_t)cc * ih + (oy * sh + ky)) * iw + (ox * sw + kx)];
                        if (v > m) m = v;
                    }
                out[((size_t)cc * oh + oy) * ow + ox] = m;
            }
}

static void fc_sw(const lprnet_layer_t *L, const uint8_t *in, int32_t *out)
{
    const int8_t *w = W(L);
    const int32_t *b = B(L);
    int n = L->in_ch, m = L->out_ch;
    int o, i;
    for (o = 0; o < m; ++o) {
        int32_t acc = b[o];
        const int8_t *wp = w + (size_t)o * n;
        for (i = 0; i < n; ++i)
            acc += (int32_t)wp[i] * (int32_t)in[i];
        out[o] = acc;
    }
}

void lprnet_accel_infer(const uint8_t *img32x128, uint8_t out_cls[7], int32_t *out_scores,
                        uint8_t *work0, uint8_t *work1)
{
    int c = 1, h = LPRNET_IN_H, w = LPRNET_IN_W;
    const uint8_t *src = img32x128;
    uint8_t *buf[2] = { work0, work1 };
    int cur = 0;
    int i;

    for (i = 0; i < LPRNET_NUM_LAYERS; ++i) {
        const lprnet_layer_t *L = &LPRNET_LAYERS[i];
        if (L->type == 0) {
            if (i == 0)
                conv1_sw(L, src, h, w, buf[cur]);        /* conv1 太小，软件算 */
            else
                accel_conv(L, src, h, w, buf[cur]);      /* conv2/3/4 走 FPGA */
            c = L->out_ch;
        } else if (L->type == 1) {
            pool_sw(L, src, c, h, w, buf[cur]);
            h /= L->stride_h;
            w /= L->stride_w;
        } else {
            fc_sw(L, src, out_scores);
            break;
        }
        src = buf[cur];
        cur ^= 1;
    }

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
