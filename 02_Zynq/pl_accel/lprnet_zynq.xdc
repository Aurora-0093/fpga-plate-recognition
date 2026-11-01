#=============================================================================
# lprnet_zynq 引脚约束 —— 正点原子 领航者 ZYNQ7020（ATK_ZYNQ_CORE 核心板）
#
# 引脚来源：《领航者ZYNQ IO引脚分配总表.xlsx》
#
#   uart_img_rxd = T19  ← ATK MODULE 接口的 RXD（UART3_RX），板上无芯片驱动，空闲
#                         用杜邦线接 20K 板的 UART TX
#   uart_img_txd = J15  ← ATK MODULE 接口的 TXD（备用，可不接）
#   led[0] = H15       ← 底板 PL_LED0
#   led[1] = L15       ← 底板 PL_LED1
#
# PS 侧的 DDR / UART0(MIO14/15) / QSPI 由 PS7 硬核自动处理，无需在此约束。
#=============================================================================

set_property -dict {PACKAGE_PIN T19 IOSTANDARD LVCMOS33} [get_ports uart_img_rxd]
set_property -dict {PACKAGE_PIN J15 IOSTANDARD LVCMOS33} [get_ports uart_img_txd]
set_property -dict {PACKAGE_PIN H15 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN L15 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
