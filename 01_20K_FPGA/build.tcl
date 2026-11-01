# Gowin command-line full build: synthesis + place & route + bitstream
# Usage: double-click build.bat, or run in this directory:
#   "D:\Gowin_V1.9.12.04_x64_win\Gowin\Gowin_V1.9.12.04_x64\IDE\bin\gw_sh.exe" < build.tcl
# Output: impl/pnr/fpga_projectnumber.fs

set_device GW2A-LV18PG256C8/I7 -name GW2A-18C

add_file -type verilog "src/DDR3MI.v"
add_file -type verilog "src/Sobel_Edge_Detector.v"
add_file -type verilog "src/VIP_Bit_Dilation_Detector.v"
add_file -type verilog "src/VIP_Bit_Erosion_Detector.v"
add_file -type verilog "src/VIP_horizon_projection.v"
add_file -type verilog "src/VIP_vertical_projection.v"
add_file -type verilog "src/Video_Frame_Buffer_Top.v"
add_file -type verilog "src/binarization.v"
add_file -type verilog "src/cmos_8_16bit.v"
add_file -type verilog "src/cmos_pll.v"
add_file -type verilog "src/gowin_sdpb_1024x10.v"
add_file -type verilog "src/gowin_sdpb_1024x8.v"
add_file -type verilog "src/i2c_config.v"
add_file -type verilog "src/i2c_master_bit_ctrl.v"
add_file -type verilog "src/i2c_master_byte_ctrl.v"
add_file -type verilog "src/i2c_master_defines.v"
add_file -type verilog "src/i2c_master_top.v"
add_file -type verilog "src/image_process.v"
add_file -type verilog "src/line_shift_ram_8bit.v"
add_file -type verilog "src/lut_ov5640_rgb565_480_272.v"
add_file -type verilog "src/matrix_generate_3x3_1bit.v"
add_file -type verilog "src/matrix_generate_3x3_8bit.v"
add_file -type verilog "src/mem_pll.v"
add_file -type verilog "src/para.v"
add_file -type verilog "src/rgb2ycbcr.v"
add_file -type verilog "src/syn_gen.v"
add_file -type verilog "src/sys_pll.v"
add_file -type verilog "src/timescale.v"
add_file -type verilog "src/top.v"
add_file -type verilog "src/video_fifo.v"

add_file -type cst "src/top.cst"
add_file -type sdc "src/lcd.sdc"

set_option -top_module top
set_option -output_base_name fpga_projectnumber
set_option -use_sspi_as_gpio 1

run all
exit
