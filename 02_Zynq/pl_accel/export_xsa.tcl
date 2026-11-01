open_project D:/fpga_plate_recognition/zynq_project/lprnet_zynq/lprnet_zynq.xpr
puts "PROJ_OPENED"
open_run impl_1
puts "RUN_OPENED"
write_hw_platform -fixed -include_bit -force D:/fpga_plate_recognition/zynq_project/lprnet_zynq/system_wrapper.xsa
puts "XSA_DONE"
exit
