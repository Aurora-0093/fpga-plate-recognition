
module VIP_Bit_Erosion_Detector
#(
	parameter	[9:0]	IMG_HDISP = 10'd480,
	parameter	[9:0]	IMG_VDISP = 10'd272
)
(

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
	output				post_img_Bit		
);


wire			matrix_frame_vsync;
wire			matrix_frame_href;
wire			matrix_frame_clken;
wire			matrix_p11, matrix_p12, matrix_p13;	
wire			matrix_p21, matrix_p22, matrix_p23;
wire			matrix_p31, matrix_p32, matrix_p33;

matrix_generate_3x3_1bit u_matrix_generate_3x3_1bit(

	.clk					(clk), 
	.rst_n					(rst_n),

	//前
	.per_frame_vsync		(per_frame_vsync),
	.per_frame_href			(per_frame_href),
	.per_frame_clken		(per_frame_clken),
	.per_img_y			    (per_img_Bit),	


	.matrix_frame_vsync		(matrix_frame_vsync),	
	.matrix_frame_href		(matrix_frame_href),	
	.matrix_frame_clken		(matrix_frame_clken),	
	.matrix_p11(matrix_p11),	.matrix_p12(matrix_p12), 	.matrix_p13(matrix_p13),	
	.matrix_p21(matrix_p21), 	.matrix_p22(matrix_p22), 	.matrix_p23(matrix_p23),
	.matrix_p31(matrix_p31), 	.matrix_p32(matrix_p32), 	.matrix_p33(matrix_p33)
);


reg	post_img_Bit1,	post_img_Bit2,	post_img_Bit3;
always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)
		begin
		post_img_Bit1 <= 1'b0;
		post_img_Bit2 <= 1'b0;
		post_img_Bit3 <= 1'b0;
		end
	else
		begin
		post_img_Bit1 <= matrix_p11 & matrix_p12 & matrix_p13;
		post_img_Bit2 <= matrix_p21 & matrix_p22 & matrix_p23;
		post_img_Bit3 <= matrix_p21 & matrix_p32 & matrix_p33;
		end
end

reg	post_img_Bit4;
always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)
		post_img_Bit4 <= 1'b0;
	else
		post_img_Bit4 <= post_img_Bit1 & post_img_Bit2 & post_img_Bit3;
end

//同步
reg	[1:0]	per_frame_vsync_r;
reg	[1:0]	per_frame_href_r;	
reg	[1:0]	per_frame_clken_r;
always@(posedge clk or negedge rst_n)
begin
	if(!rst_n)
		begin
		per_frame_vsync_r <= 0;
		per_frame_href_r <= 0;
		per_frame_clken_r <= 0;
		end
	else
		begin
		per_frame_vsync_r 	<= 	{per_frame_vsync_r[0], 	matrix_frame_vsync};
		per_frame_href_r 	<= 	{per_frame_href_r[0], 	matrix_frame_href};
		per_frame_clken_r 	<= 	{per_frame_clken_r[0], 	matrix_frame_clken};
		end
end
assign	post_frame_vsync 	= 	per_frame_vsync_r[1];
assign	post_frame_href 	= 	per_frame_href_r[1];
assign	post_frame_clken 	= 	per_frame_clken_r[1];
assign	post_img_Bit		=	post_frame_href ? post_img_Bit4 : 1'b0;

endmodule
