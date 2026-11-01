module cmos_8_16bit(
	input              rst,
	input              pclk,
	input [7:0]        pdata_i,
	input              de_i,
	output reg[15:0]   pdata_o,
	output reg	       hblank,
	output reg         de_o
);
reg[7:0] pdata_i_d0;
reg x_cnt;
reg de_d1, de_d2;      // 补上缺失的声明

always@(negedge pclk)  // 改成下降沿采样
begin
	pdata_i_d0 <= pdata_i;
    de_d1 <= de_i;     // 补上 de_d1 的赋值
    de_d2 <= de_d1;    // 补上 de_d2 的赋值
end

always@(negedge pclk)  // 改成下降沿
begin
	if(de_i & !de_d1)
		x_cnt <= 1;
	else
		x_cnt <= ~x_cnt ;
end

always@(negedge pclk or posedge rst)  // 改成下降沿
begin
	if(rst)
		de_o <= 1'b0;
	else if(x_cnt)
		de_o <= 1'b1;
	else
		de_o <= 1'b0;
end

always@(negedge pclk)  // 改成下降沿
begin
 	hblank <= de_d2;
end 

always@(negedge pclk or posedge rst)  // 改成下降沿
begin
	if(rst)
		pdata_o <= 16'd0;
	else if(de_i && x_cnt)
		pdata_o <= {pdata_i_d0,pdata_i};
	else
		pdata_o <= pdata_o;
end

endmodule