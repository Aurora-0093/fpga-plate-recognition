`timescale 1ns/1ns
module VIP_horizon_projection # (
	parameter	[9:0]	IMG_HDISP = 10'd480,
	parameter	[9:0]	IMG_VDISP = 10'd272
)(

	input				clk,  
	input				rst_n,

	//前
	input				per_frame_vsync,
	input				per_frame_href,	
	input				per_frame_clken,
	input				per_img_Bit,	
	
	//后
	output				post_frame_vsync,	
	output				post_frame_href,	
	output				post_frame_clken,	
	output				post_img_Bit, 		

    output reg [9:0] 	max_line_up , 
    output reg [9:0] 	max_line_down,
	
    input      [9:0] 	horizon_start,
    input      [9:0] 	horizon_end	 
);

reg [9:0] 	max_pixel_up  ;
reg [9:0] 	max_pixel_down;

reg			per_frame_vsync_r;
reg			per_frame_href_r;	
reg			per_frame_clken_r;
reg  		per_img_Bit_r;

reg			per_frame_vsync_r2;
reg			per_frame_href_r2;	
reg			per_frame_clken_r2;
reg         per_img_Bit_r2;

assign	post_frame_vsync 	= 	per_frame_vsync_r2;
assign	post_frame_href 	= 	per_frame_href_r2;	
assign	post_frame_clken 	= 	per_frame_clken_r2;
assign  post_img_Bit     	=   per_img_Bit_r2;


//打拍
always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)
		begin
		per_frame_vsync_r2 	<= 0;
		per_frame_href_r2 	<= 0;
		per_frame_clken_r2 	<= 0;
		per_img_Bit_r2		<= 0;
		end
	else
		begin
		per_frame_vsync_r2 	<= 	per_frame_vsync_r 	;
		per_frame_href_r2	<= 	per_frame_href_r 	;
		per_frame_clken_r2 	<= 	per_frame_clken_r 	;
		per_img_Bit_r2		<= 	per_img_Bit_r		;
		end
end

always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)
		begin
		per_frame_vsync_r 	<= 0;
		per_frame_href_r 	<= 0;
		per_frame_clken_r 	<= 0;
		per_img_Bit_r		<= 0;
		end
	else
		begin
		per_frame_vsync_r 	<= 	per_frame_vsync	;
		per_frame_href_r	<= 	per_frame_href	;
		per_frame_clken_r 	<= 	per_frame_clken	;
		per_img_Bit_r	    <= 	per_img_Bit		;
		end
end

//取边沿
wire vsync_pos_flag;
wire vsync_neg_flag;
wire hrefr_pos_flag;
wire hrefr_neg_flag;
assign vsync_pos_flag =   per_frame_vsync_r  & (~per_frame_vsync_r2);
assign vsync_neg_flag = (~per_frame_vsync_r) &   per_frame_vsync_r2;
assign hrefr_pos_flag =   per_frame_href_r  & (~per_frame_href_r2);
assign hrefr_neg_flag = (~per_frame_href_r) & per_frame_href_r2;


//获取像素坐标
reg [9:0]  	x_cnt;
reg [9:0]   y_cnt;
always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)begin
        x_cnt <= 10'd0;
        y_cnt <= 10'd0;
    end
	else if(vsync_neg_flag)begin
        x_cnt <= 10'd0;
        y_cnt <= 10'd0;
    end
    else if(hrefr_neg_flag)begin
        x_cnt <= 10'd0;
        y_cnt <= y_cnt + 1'b1;
    end
    else if(per_frame_clken_r) begin
        x_cnt <= x_cnt + 1'b1;
    end
end


reg [9:0]  	x_cnt_r;
reg [9:0]   y_cnt_r;

always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)
		begin
			x_cnt_r <= 10'd0;
			y_cnt_r <= 10'd0;
		end
	else begin
			x_cnt_r <= x_cnt;
            y_cnt_r <= y_cnt;
		end
end


//ram缓存
reg  		ram_wr;
reg  [9:0] 	ram_wr_data;
wire [9:0] 	ram_rd_data;
wire [9:0] ram_wr_addr;
wire [9:0] ram_rd_addr;



always @ (posedge clk or negedge rst_n) begin
    if(!rst_n) begin
        ram_wr <= 1'b0;
    end
    else if(per_frame_clken && (y_cnt != IMG_VDISP - 1'b1))
        ram_wr <= 1'b1;
    else
        ram_wr <= 1'b0;
end


always @ (posedge clk or negedge rst_n) begin
    if(!rst_n) begin
        ram_wr_data <= 10'd0;
    end
    else if(y_cnt == 10'd0)
        ram_wr_data <= 10'd0;
    else if(hrefr_pos_flag)
        ram_wr_data <= 10'd0;
    else if((x_cnt > horizon_start) && (x_cnt < horizon_end))
        ram_wr_data <= ram_wr_data + per_img_Bit_r;
end


//读写地址
assign ram_wr_addr = (y_cnt == 10'd0)  ?  x_cnt : y_cnt_r;

assign ram_rd_addr = ((y_cnt == 10'd0) || (y_cnt == IMG_VDISP - 1'b1))  ?  x_cnt : y_cnt;


projection_ram  u_projection_ram(
    .dout       (ram_rd_data), //output [9:0] dout
    .clka       (clk), //input clka
    .cea        (ram_wr), //input cea
    .reseta     (1'b0), //input reseta
    .clkb       (clk), //input clkb
    .ceb        (1'b1), //input ceb
    .resetb     (1'b0), //input resetb
    .oce        ( ), //input oce
    .ada        (ram_wr_addr), //input [9:0] ada
    .din        (ram_wr_data), //input [9:0] din
    .adb        (ram_rd_addr) //input [9:0] adb
);


reg [9:0] rd_data_d1;
reg [9:0] rd_data_d2;
reg [9:0] rd_data_d3;

always @ (posedge clk or negedge rst_n) begin
    if(!rst_n) begin
        rd_data_d1 <= 10'd0;
        rd_data_d2 <= 10'd0;
    end
    else if(per_frame_clken) begin
        rd_data_d1 <= ram_rd_data;
        rd_data_d2 <= rd_data_d1;
        rd_data_d3 <= rd_data_d2;
	end
end

reg [9:0] max_num1  ;
reg [9:0] max_y1    ;
reg [9:0] max_num2  ;
reg [9:0] max_y2    ;

always @ (posedge clk or negedge rst_n) begin
    if(!rst_n) begin
        max_y1   <= 10'd0;
        max_num1 <= 10'd0;
        max_y2   <= 10'd0;
        max_num2 <= 10'd0;
    end
    else if(per_frame_clken) begin

        if(y_cnt == IMG_VDISP - 1'b1) begin    //投影开始
		    //梯度判断
			if( (rd_data_d2 > rd_data_d1) && (rd_data_d2>10'd50))begin
			    max_y1		<= x_cnt_r-3;
				max_num1	<= rd_data_d1;
			end	
			//梯度判断
			if( (rd_data_d2 < rd_data_d1) && (rd_data_d1>10'd50) && (max_y2==10'd0)) begin
			    max_y2   	<= x_cnt_r-3;
				max_num2  	<= rd_data_d1;
			end
        end
		else begin
            max_y1 <= max_y1;
            max_y2 <= max_y2;
        end
	end
	else if(vsync_neg_flag)begin
        max_y1   <= 10'd0;
        max_num1 <= 10'd0;
        max_y2   <= 10'd0;
        max_num2 <= 10'd0;
    end
end

always @ (posedge clk or negedge rst_n) begin
    if(!rst_n) begin
        max_line_up  <= 10'd0;
        max_line_down <= 10'd0;
        max_pixel_up  <= 10'd0;
        max_pixel_down <= 10'd0;
    end
    else if(vsync_pos_flag) begin
		max_line_up   <= max_y1;
		max_pixel_up  <= max_num1;
		
		max_line_down  <= max_y2;
		max_pixel_down <= max_num2;
    end   
end
	
endmodule
