set proj_root "D:/fpga_plate_recognition/zynq_project"
set proj_name "lprnet_zynq"
source $proj_root/create_bd.tcl
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
puts "IMPL_DONE"
puts "比特流在: $proj_root/$proj_name/$proj_name.runs/impl_1/system_wrapper.bit"
puts "接下来手动导出 XSA: vivado -mode batch -source export_xsa.tcl -notrace"
exit