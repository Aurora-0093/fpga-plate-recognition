/* 自动生成：AE350 软件推理用 LPRNet 层描述（int8 权重 + int32 bias） */
#ifndef LPRNET_SW_H
#define LPRNET_SW_H
#include <stdint.h>

#define LPRNET_IN_H      32
#define LPRNET_IN_W      128
#define LPRNET_CLASSES   41
#define LPRNET_TIMESTEPS 7
#define LPRNET_BIN_SIZE  5092636
#define LPRNET_NUM_LAYERS 9

typedef struct {
    uint8_t  type;           /* 0=conv 1=pool 2=fc */
    uint16_t in_ch;          /* conv: 输入通道 / fc: in_features */
    uint16_t out_ch;         /* conv: 输出通道 / fc: out_features */
    uint8_t  kh, kw, stride_h, stride_w, pad;
    uint32_t w_offset, w_len, b_offset, b_len;
    float    w_scale, a_scale, out_scale;
} lprnet_layer_t;

static const lprnet_layer_t LPRNET_LAYERS[9] = {
    {0, 1, 32, 3, 3, 1, 1, 1, 0u, 288u, 288u, 32u, 0.026624235f, 0.003921569f, 0.027116617f},
    {1, 0, 0, 2, 2, 2, 2, 0, 0u, 0u, 0u, 0u, 0.0f, 0.027116617f, 0.027116617f},
    {0, 32, 64, 3, 3, 1, 1, 1, 416u, 18432u, 18848u, 64u, 0.000973665f, 0.027116617f, 0.024888708f},
    {1, 0, 0, 2, 2, 2, 2, 0, 0u, 0u, 0u, 0u, 0.0f, 0.024888708f, 0.024888708f},
    {0, 64, 128, 3, 3, 1, 1, 1, 19104u, 73728u, 92832u, 128u, 0.000792839f, 0.024888708f, 0.019181068f},
    {1, 0, 0, 2, 1, 2, 1, 0, 0u, 0u, 0u, 0u, 0.0f, 0.019181068f, 0.019181068f},
    {0, 128, 256, 3, 3, 1, 1, 1, 93344u, 294912u, 388256u, 256u, 0.000495501f, 0.019181068f, 0.017992008f},
    {1, 0, 0, 2, 1, 2, 1, 0, 0u, 0u, 0u, 0u, 0.0f, 0.017992008f, 0.017992008f},
    {2, 16384, 287, 0, 0, 1, 1, 0, 389280u, 4702208u, 5091488u, 287u, 0.001610632f, 0.017992008f, 0.0f},
};

/* 软件推理接口（实现在 lprnet_sw.c） */
void lprnet_sw_init(const uint8_t *bin, uint32_t bin_size);
/* 输入 32*128 uint8 灰度，输出 7 个字符类别下标（0..38）。
   work0/work1 为两个工作缓冲，各 >= 32*32*128 = 131072 字节。 */
void lprnet_sw_infer(const uint8_t *img32x128, uint8_t out_cls[7], int32_t *out_scores,
                     uint8_t *work0, uint8_t *work1);

#endif
