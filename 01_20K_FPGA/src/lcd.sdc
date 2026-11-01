# 1. FPGA 系统主时钟 27MHz 
create_clock -name clk -period 37.037 [get_ports {clk}]

# 2. 摄像头 PCLK 时钟 
create_clock -name cmos_pclk -period 40 [get_ports {cmos_pclk}]

# 3. 内部摄像头采集时钟
create_clock -name cmos_16bit_clk -period 40 [get_nets {cmos_16bit_clk}]

# 4. DDR3 内存控制器时钟 400MHz 
create_clock -name mem_clk -period 2.5 -waveform {0 1.25} [get_nets {memory_clk}]

# 5. 时序报告命令
report_timing -hold -from_clock [get_clocks {clk*}] -to_clock [get_clocks {clk*}] -max_paths 25 -max_common_paths 1
report_timing -setup -from_clock [get_clocks {clk*}] -to_clock [get_clocks {clk*}] -max_paths 25 -max_common_paths 1