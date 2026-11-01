/* FPGA 卷积加速器驱动（Zynq-7020） */
#ifndef LPRNET_ACCEL_H
#define LPRNET_ACCEL_H
#include <stdint.h>

/* 初始化：把 conv2/3/4 的权重重排成 16 通道打包布局写进 BRAM（开机调一次） */
void lprnet_accel_init(void);

/* 加速推理：conv1/pool/FC 用软件，conv2/3/4 用 FPGA 引擎。
   输入 32x128 uint8 灰度，输出 7 个字符类别下标 + 分数。 */
void lprnet_accel_infer(const uint8_t *img32x128, uint8_t out_cls[7], int32_t *out_scores,
                        uint8_t *work0, uint8_t *work1);

#endif
