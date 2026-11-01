module line_shift_ram_8bit(
    input          clock,   
    input          clken,
    input          per_frame_href,
    
    input   [7:0]  shiftin,  
    output  [7:0]  taps0x,   
    output  [7:0]  taps1x    
);


reg  [2:0]  clken_dly;
reg  [9:0]  ram_rd_addr;
reg  [9:0]  ram_rd_addr_d0;
reg  [9:0]  ram_rd_addr_d1;
reg  [7:0]  shiftin_d0;
reg  [7:0]  shiftin_d1;
reg  [7:0]  shiftin_d2;
reg  [7:0]  taps0x_d0;



//两行缓存
always@(posedge clock)begin
    if(per_frame_href)
        if(clken)
            ram_rd_addr <= ram_rd_addr + 1 ;
        else
            ram_rd_addr <= ram_rd_addr ;
    else
        ram_rd_addr <= 0 ;
end


always@(posedge clock) begin
    clken_dly <= { clken_dly[1:0] , clken };
end



always@(posedge clock ) begin
    ram_rd_addr_d0 <= ram_rd_addr;
    ram_rd_addr_d1 <= ram_rd_addr_d0;
end


always@(posedge clock)begin
    shiftin_d0 <= shiftin;
    shiftin_d1 <= shiftin_d0;
    shiftin_d2 <= shiftin_d1;
end


blk_mem u_ram_1024x8_0(
    .dout       (taps0x), //output [7:0] dout
    .clka       (clock), //input clka
    .cea        (clken_dly[2] ), //input cea
    .reseta     (1'b0), //input reseta
    .clkb       (clock), //input clkb
    .ceb        (1'b1), //input ceb
    .resetb     (1'b0), //input resetb
    .oce        ( ), //input oce
    .ada        (ram_rd_addr_d1), //input [9:0] ada
    .din        (shiftin_d2), //input [7:0] din
    .adb        (ram_rd_addr) //input [9:0] adb
);

always@(posedge clock ) begin
    taps0x_d0 <= taps0x;
end


blk_mem u_ram_1024x8_1(
    .dout       (taps1x), //output [7:0] dout
    .clka       (clock), //input clka
    .cea        (clken_dly[1] ), //input cea
    .reseta     (1'b0), //input reseta
    .clkb       (clock), //input clkb
    .ceb        (1'b1), //input ceb
    .resetb     (1'b0), //input resetb
    .oce        ( ), //input oce
    .ada        (ram_rd_addr_d0), //input [9:0] ada
    .din        (taps0x_d0), //input [7:0] din
    .adb        (ram_rd_addr) //input [9:0] adb
);


endmodule 