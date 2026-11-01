/*
 * LPRNet 车牌识别 - Zynq-7020 裸机程序（41 类，支持带颜色/距离的扩展帧）
 *
 * 数据通路（双输入）：
 *   ① 20K 板 TX ──> PL T19 (AXI UART Lite rx)  ──┐
 *                                                  ├─> 收帧 -> 推理 -> 输出
 *   ② PC 串口  ──> PS UART0 (MIO14/15)         ──┘
 *
 * 支持的帧格式（与 uart_aa55_capture.py 一致，自动识别）：
 *   AA 55 + 4096 像素 + [颜色1B] + [距离H 距离L] + 0D 0A
 *   = 4100 / 4101 / 4102 / 4103 字节
 *
 * 输出（PS UART0，115200）：
 *   PLATE:<车牌>,<置信度>      例：PLATE:粤C54321,0.93
 *   INFO:<颜色字节>,<距离mm>   例：INFO:2,350
 */
#include <stdint.h>
#include <math.h>
#include "xparameters.h"
#include "xuartps.h"
#include "xuartlite.h"
#include "xgpio.h"
#include "lprnet_sw.h"
#include "lprnet_accel.h"

#define IMG_BYTES       (128u * 32u)

/* 电脑端串口波特率 */
#define PC_BAUD         921600u
#define FRAME_H0        0xAA
#define FRAME_H1        0x55
#define FRAME_T0        0x0D
#define FRAME_T1        0x0A

/* AXI UART Lite 的基地址宏：SDT 流程下可能是 XPAR_XUARTLITE_0_BASEADDR
 * 或按实例名生成的 XPAR_UART_IMG_BASEADDR，两种都兼容 */
#if defined(XPAR_XUARTLITE_0_BASEADDR)
#define UART_IMG_BASE   XPAR_XUARTLITE_0_BASEADDR
#elif defined(XPAR_UART_IMG_BASEADDR)
#define UART_IMG_BASE   XPAR_UART_IMG_BASEADDR
#else
#define UART_IMG_BASE   0x41200000U
#endif

extern const unsigned char lprnet_weights[];
extern const unsigned int  lprnet_weights_len;

static XUartPs   ps_uart;
static XUartLite img_uart;
static XGpio     led_gpio;
static UINTPTR   uart_base;

static uint8_t  img_buf[IMG_BYTES];
static uint8_t  work0[32 * 32 * 128];
static uint8_t  work1[32 * 32 * 128];
static uint8_t  cls[LPRNET_TIMESTEPS];
static uint8_t  cls_sw[LPRNET_TIMESTEPS];
static int32_t  scores_sw[LPRNET_CLASSES * LPRNET_TIMESTEPS];
static int32_t  scores[LPRNET_CLASSES * LPRNET_TIMESTEPS];

/* 帧尾附加信息 */
static uint8_t  fr_color = 0xFF;   /* 0xFF = 本帧无颜色字节 */
static uint16_t fr_dist  = 0;      /* 0 = 未测距 */

/* 41 类：36 字母数字 + 沪陕粤贵赣（与 3_train.py 一致） */
static const char *const lprnet_chars[LPRNET_CLASSES] = {
    "0","1","2","3","4","5","6","7","8","9",
    "A","B","C","D","E","F","G","H","I","J",
    "K","L","M","N","O","P","Q","R","S","T",
    "U","V","W","X","Y","Z","沪","陕","粤","贵","赣"
};

/*输出：同时打到 PS UART0 和 PL UART Lite*/
static int img_uart_ready = 0;

static void uputs(const char *s)
{
    while (*s) {
        u8 c = (u8)(*s++);
        XUartPs_SendByte(uart_base, c);                       /* PS 串口（USB Type-C） */
        if (img_uart_ready)
            XUartLite_Send(&img_uart, &c, 1);                 /* PL 串口（ATK 排母 J15） */
    }
}

static void uput_u32(uint32_t v)
{
    char b[11];
    int i = 10;
    b[i] = 0;
    if (v == 0) { b[--i] = '0'; }
    while (v && i > 0) { b[--i] = (char)('0' + v % 10); v /= 10; }
    uputs(&b[i]);
}

/* 0.00 ~ 1.00，两位小数（不依赖 printf 浮点） */
static void uput_conf(float c)
{
    char b[6];
    int v = (int)(c * 100.0f + 0.5f);

    if (v < 0) v = 0;
    if (v >= 100) {                 /* 1.00 单独处理，避免十位溢出成 ':' */
        uputs("1.00");
        return;
    }
    b[0] = '0'; b[1] = '.';
    b[2] = (char)('0' + v / 10);
    b[3] = (char)('0' + v % 10);
    b[4] = 0;
    uputs(b);
}

/*双输入取字节*/
static int ugetc_any(void)
{
    u8 b;

    for (;;) {
        if (XUartLite_Recv(&img_uart, &b, 1) == 1)
            return (int)b;
        if (XUartPs_IsReceiveData(uart_base))
            return (int)XUartPs_RecvByte(uart_base);
    }
}

/* 收一帧；成功返回 1，并填充 img_buf / fr_color / fr_dist */
static int rx_frame(void)
{
    int b;
    uint32_t i;
    uint8_t tr[6];
    int n = 0;

    /* 同步帧头 AA 55 */
    do {
        b = ugetc_any();
    } while (b != FRAME_H0 || ugetc_any() != FRAME_H1);

    for (i = 0; i < IMG_BYTES; ++i)
        img_buf[i] = (uint8_t)ugetc_any();

    /* 收集 0~3 个附加字节，直到出现 0D 0A */
    for (;;) {
        tr[n++] = (uint8_t)ugetc_any();
        if (n >= 2 && tr[n - 2] == FRAME_T0 && tr[n - 1] == FRAME_T1) {
            n -= 2;              /* n = 附加字节个数 */
            break;
        }
        if (n >= 5) return 0;    /* 帧异常 */
    }

    fr_color = 0xFF;
    fr_dist  = 0;
    if (n == 1) {                       /* 颜色帧 */
        fr_color = tr[0];
    } else if (n == 2) {                /* 距离帧 */
        fr_dist = (uint16_t)((tr[0] << 8) | tr[1]);
    } else if (n == 3) {                /* 合并帧：颜色 + 距离 */
        fr_color = tr[0];
        fr_dist  = (uint16_t)((tr[1] << 8) | tr[2]);
    }
    return 1;
}

/* 不依赖 libm 的 exp 近似（输入 <= 0，用于 softmax） */
static float fast_exp(float x)
{
    union { float f; uint32_t i; } u;
    float y, frac, p;
    int n;

    if (x < -80.0f) return 0.0f;
    y = x * 1.4426950408889634f;      /* exp(x) = 2^(x*log2e) */
    n = (int)y;
    if (y < 0.0f && (float)n != y) n -= 1;
    frac = y - (float)n;              /* [0,1) */
    p = 1.0f + frac * (0.6931472f + frac * (0.2402265f + frac * 0.0555041f));
    u.i = (uint32_t)((n + 127) << 23);
    return u.f * p;
}

/* softmax 最大概率的 7 步平均 */
static float scores_conf(const int32_t *sc)
{
    float tot = 0.0f;
    int t, k;

    for (t = 0; t < LPRNET_TIMESTEPS; ++t) {
        const int32_t *row = sc + t * LPRNET_CLASSES;
        int32_t mx = row[0];
        float sum = 0.0f, best = 0.0f;

        for (k = 1; k < LPRNET_CLASSES; ++k)
            if (row[k] > mx) mx = row[k];

        for (k = 0; k < LPRNET_CLASSES; ++k) {
            float e = fast_exp((float)(row[k] - mx));
            sum += e;
            if (row[k] == mx) best = e;
        }
        tot += (sum > 0.0f) ? (best / sum) : 0.0f;
    }
    return tot / (float)LPRNET_TIMESTEPS;
}

int main(void)
{
    XUartPs_Config   *pcfg;
    XUartLite_Config *ucfg;
    int st;

    /*阶段 1：只初始化 PS 串口，立刻打印*/
    pcfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    if (pcfg == NULL) return -1;
    XUartPs_CfgInitialize(&ps_uart, pcfg, pcfg->BaseAddress);
    uart_base = pcfg->BaseAddress;
    XUartPs_SetBaudRate(&ps_uart, PC_BAUD);
    uputs("\r\n[1] PS UART0 OK (MIO14/15)\r\n");

    /*阶段 2：PL 的 AXI UART Lite（T19）*/
    ucfg = XUartLite_LookupConfig(UART_IMG_BASE);
    if (ucfg != NULL) {
        XUartLite_CfgInitialize(&img_uart, ucfg, UART_IMG_BASE);
        img_uart_ready = 1;
        uputs("[2] PL UART Lite OK\n");
    } else {
        uputs("[2] PL UART Lite NOT FOUND\n");
    }

    /* 阶段 3：PL 的 AXI GPIO（LED）*/
    st = XGpio_Initialize(&led_gpio, XPAR_GPIO_LED_BASEADDR);
    if (st == XST_SUCCESS) {
        XGpio_SetDataDirection(&led_gpio, 1, 0x0);
        XGpio_DiscreteWrite(&led_gpio, 1, 0x3);
        uputs("[3] PL GPIO OK\n");
    } else {
        uputs("[3] PL GPIO FAILED\n");
    }

    /* 阶段 4：加载权重 */
    lprnet_sw_init(lprnet_weights, lprnet_weights_len);
    uputs("[4] weights ");
    uput_u32(lprnet_weights_len);
    uputs(" bytes ready\n");

    lprnet_accel_init();
    uputs("[5] accel weights repacked\n");

    uputs("LPRNet ready, 41 classes\n");

    for (;;) {
        uputs("waiting frame...\r\n");
        while (!rx_frame()) { }

        XGpio_DiscreteWrite(&led_gpio, 1, 0x3);

        lprnet_sw_infer(img_buf, cls_sw, scores_sw, work0, work1);
        lprnet_accel_infer(img_buf, cls, scores, work0, work1);
        {   int m = 1; uint32_t tt;
            for (tt = 0; tt < LPRNET_TIMESTEPS; ++tt) if (cls_sw[tt] != cls[tt]) m = 0;
            uputs("DBG: SW="); for (tt = 0; tt < LPRNET_TIMESTEPS; ++tt) uputs(lprnet_chars[cls_sw[tt]]);
            uputs(" ACCEL="); for (tt = 0; tt < LPRNET_TIMESTEPS; ++tt) uputs(lprnet_chars[cls[tt]]);
            uputs(m ? " MATCH\r\n" : " DIFF\r\n"); }

        uputs("PLATE:");
        for (uint32_t t = 0; t < LPRNET_TIMESTEPS; ++t)
            uputs(lprnet_chars[cls[t]]);
        uputs(",");
        uput_conf(scores_conf(scores));
        uputs("\r\n");

        uputs("INFO:");
        if (fr_color == 0xFF) uputs("255"); else uput_u32(fr_color);
        uputs(",");
        uput_u32(fr_dist);
        uputs("\r\n");

        /* 把收到的灰度图回显给 PC（网页显示用，格式：IMG:<字节数>\r\n + 原始数据） */
        uputs("IMG:4096\r\n");
        for (uint32_t i = 0; i < IMG_BYTES; ++i)
            XUartPs_SendByte(uart_base, img_buf[i]);
        uputs("\r\n");

        XGpio_DiscreteWrite(&led_gpio, 1, 0x0);
    }
    return 0;
}
