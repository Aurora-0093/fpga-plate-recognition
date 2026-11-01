module top(
	input                       clk,
    input                       key_in,
	input                       rst_n,
	inout                       cmos_scl,
	inout                       cmos_sda,
	input                       cmos_vsync,
	input                       cmos_href,
	input                       cmos_pclk,
    output                      cmos_xclk,
	input   [7:0]               cmos_db,
	output                      cmos_rst_n,
	output                      cmos_pwdn,
	
	output [3:0] 				state_led,

	output [14-1:0]             ddr_addr,
	output [3-1:0]              ddr_bank,
	output                      ddr_cs,
	output                      ddr_ras,
	output                      ddr_cas,
	output                      ddr_we,
	output                      ddr_ck,
	output                      ddr_ck_n,
	output                      ddr_cke,
	output                      ddr_odt,
	output                      ddr_reset_n,
	output [2-1:0]              ddr_dm,
	inout [16-1:0]              ddr_dq,
	inout [2-1:0]               ddr_dqs,
	inout [2-1:0]               ddr_dqs_n,

	output                      lcd_dclk,	
	output                      lcd_hs,
	output                      lcd_vs,
	output                      lcd_de,
	output[4:0]                 lcd_r,
	output[5:0]                 lcd_g,
	output[4:0]                 lcd_b,

    output                      uart_tx      ,   
    output                      uart_tx_gpio     
);

// 存储器接口
wire                   memory_clk         ;
wire                   dma_clk         	  ;
wire                   pll_lock           ;
wire                   cmd_ready          ;
wire[2:0]              cmd                ;
wire                   cmd_en             ;
wire[5:0]              app_burst_number   ;
wire[ADDR_WIDTH-1:0]   addr               ;
wire                   wr_data_rdy        ;
wire                   wr_data_en         ;
wire                   wr_data_end        ;
wire[DATA_WIDTH-1:0]   wr_data            ;   
wire[DATA_WIDTH/8-1:0] wr_data_mask       ;   
wire                   rd_data_valid      ;  
wire                   rd_data_end        ;
wire[DATA_WIDTH-1:0]   rd_data            ;   
wire                   init_calib_complete;

// 按 IP 参数选择
`define	    WR_VIDEO_WIDTH_16
`define	DEF_WR_VIDEO_WIDTH 16

`define	    RD_VIDEO_WIDTH_16
`define	DEF_RD_VIDEO_WIDTH 16

`define	USE_THREE_FRAME_BUFFER

`define	DEF_ADDR_WIDTH 28 
`define	DEF_SRAM_DATA_WIDTH 128

parameter ADDR_WIDTH          = `DEF_ADDR_WIDTH;
parameter DATA_WIDTH          = `DEF_SRAM_DATA_WIDTH;
parameter WR_VIDEO_WIDTH      = `DEF_WR_VIDEO_WIDTH;  
parameter RD_VIDEO_WIDTH      = `DEF_RD_VIDEO_WIDTH;  

wire                            video_clk;

wire                      syn_off0_re;
wire                      syn_off0_vs;
wire                      syn_off0_hs;
                          
wire                      off0_syn_de  ;
wire [RD_VIDEO_WIDTH-1:0] off0_syn_data;

wire[15:0]                      cmos_16bit_data;
wire                            cmos_16bit_clk;
wire[15:0] 						write_data;

wire[9:0]                       lut_index;
wire[31:0]                      lut_data;

wire                            cmos_clk;      
wire                            cmos_16bit_wr; 

assign cmos_xclk = 1'b0;
assign cmos_pwdn = 1'b0;
assign cmos_rst_n = 1'b1;
assign write_data = {cmos_16bit_data[4:0],cmos_16bit_data[10:5],cmos_16bit_data[15:11]};

// UART 扇出
assign uart_tx_gpio = uart_tx;

// 调试：LED 显示（板载 LED 低电平点亮）
wire [3:0] state_led_debug;
assign state_led = {state_led_debug[3:1], ~init_calib_complete};

// 生成摄像头时钟和 SDRAM 控制器时钟
sys_pll sys_pll_m0(
	.clkin                     (cmos_clk                  ),
	.clkout                    (video_clk 	              )
	);
cmos_pll cmos_pll_m0(
	.clkin                     (clk                      		),
	.clkout                    (cmos_clk 	              		)
	);

mem_pll mem_pll_m0(
	.clkin                     (cmos_clk                        ),
	.clkout                    (memory_clk 	              		),
	.lock 					   (pll_lock 						)
	);

//I2C配置
i2c_config i2c_config_m0(
	.rst                        (~rst_n                   ),
	.clk                        (clk                      ),
	.clk_div_cnt                (16'd500                  ),
	.i2c_addr_2byte             (1'b1                     ),
	.lut_index                  (lut_index                ),
	.lut_dev_addr               (lut_data[31:24]          ),
	.lut_reg_addr               (lut_data[23:8]           ),
	.lut_reg_data               (lut_data[7:0]            ),
	.error                      (                         ),
	.done                       (                         ),
	.i2c_scl                    (cmos_scl                 ),
	.i2c_sda                    (cmos_sda                 )
);
//配置查找表
lut_ov5640_rgb565_480_272 lut_ov5640_rgb565_480_272_m0(
	.lut_index                  (lut_index                ),
	.lut_data                   (lut_data                 )
);
//8转16
cmos_8_16bit cmos_8_16bit_m0(
	.rst                        (~rst_n                   ),
	.pclk                       (cmos_pclk                ),
	.pdata_i                    (cmos_db                  ),
	.de_i                       (cmos_href                ),
	.pdata_o                    (cmos_16bit_data          ),
	.hblank                     (cmos_16bit_wr            ),
	.de_o                       (cmos_16bit_clk           )
);

//视频输出时序产生器
wire out_de;
syn_gen syn_gen_inst
(                                   
    .I_pxl_clk   (video_clk       ),
    .I_rst_n     (rst_n           ),
    .I_h_total   (16'd525         ),
    .I_h_sync    (16'd41          ),
    .I_h_bporch  (16'd2           ),
    .I_h_res     (16'd480         ),
    .I_v_total   (16'd284         ),
    .I_v_sync    (16'd10          ),
    .I_v_bporch  (16'd2           ),
    .I_v_res     (16'd272         ),
    .I_rd_hres   (16'd480         ),
    .I_rd_vres   (16'd272         ),
    .I_hs_pol    (1'b1            ),
    .I_vs_pol    (1'b1            ),
    .O_rden      (syn_off0_re     ),
    .O_de        (out_de          ),   
    .O_hs        (syn_off0_hs     ),
    .O_vs        (syn_off0_vs     )
);

wire        post_frame_vsync;
wire        post_frame_hsync;
wire        post_frame_de;
wire [15:0] post_rgb;

//image_process
image_process image_process_inst(
	.sys_clk		(clk),
    .clk            (cmos_16bit_clk ),
    .key_in          (key_in),   
    .rst_n          (rst_n          ),

    .pre_frame_vsync(cmos_vsync),
    .pre_frame_hsync(cmos_href),
    .pre_frame_de   (cmos_16bit_wr),
    .pre_rgb        (write_data),
    .xpos           (),
    .ypos           (),

    .post_frame_vsync(post_frame_vsync),
    .post_frame_hsync(post_frame_hsync),
    .post_frame_de   (post_frame_de),
    .post_rgb        (post_rgb),

    .state_led       (state_led_debug),
	
    .uart_tx         (uart_tx)
);

// 读写仲裁逻辑
reg  rd_halt_flag;
reg  post_frame_vsync_d1;
reg  [15:0] wr_wait_cnt;

always @(posedge cmos_16bit_clk or negedge rst_n) begin
    if (!rst_n) begin
        rd_halt_flag     <= 1'b0;
        post_frame_vsync_d1 <= 1'b1;
        wr_wait_cnt      <= 16'd0;
    end
    else begin
        post_frame_vsync_d1 <= post_frame_vsync;

        if (post_frame_vsync_d1 == 1'b1 && post_frame_vsync == 1'b0) begin
            rd_halt_flag <= 1'b1;
            wr_wait_cnt  <= 16'd0;
        end
        else if (rd_halt_flag) begin
            if (wr_wait_cnt < 16'd5000)
                wr_wait_cnt <= wr_wait_cnt + 1'b1;
            else
                rd_halt_flag <= 1'b0;
        end
    end
end

Video_Frame_Buffer_Top Video_Frame_Buffer_Top_inst
( 
    .I_rst_n              (init_calib_complete ),
    .I_dma_clk            (dma_clk          ),
`ifdef USE_THREE_FRAME_BUFFER 
    .I_wr_halt            (1'b0             ),
    .I_rd_halt            (rd_halt_flag     ),
`endif
    .I_vin0_clk           (cmos_16bit_clk   ),
    .I_vin0_vs_n          (~post_frame_vsync      ),
    .I_vin0_de            (post_frame_de    ),
    .I_vin0_data          (post_rgb  ),
    .O_vin0_fifo_full     (                 ),
    .I_vout0_clk          (video_clk        ),
    .I_vout0_vs_n         (~syn_off0_vs     ),
    .I_vout0_de           (syn_off0_re      ),
    .O_vout0_den          (off0_syn_de      ),
    .O_vout0_data         (off0_syn_data    ),
    .O_vout0_fifo_empty   (                 ),
    .I_cmd_ready          (cmd_ready          ),
    .O_cmd                (cmd                ),
    .O_cmd_en             (cmd_en             ),
    .O_app_burst_number   (app_burst_number   ),
    .O_addr               (addr               ),
    .I_wr_data_rdy        (wr_data_rdy        ),
    .O_wr_data_en         (wr_data_en         ),
    .O_wr_data_end        (wr_data_end        ),
    .O_wr_data            (wr_data            ),
    .O_wr_data_mask       (wr_data_mask       ),
    .I_rd_data_valid      (rd_data_valid      ),
    .I_rd_data_end        (rd_data_end        ),
    .I_rd_data            (rd_data            ),
    .I_init_calib_complete(init_calib_complete)
); 

localparam N = 7;
                          
reg  [N-1:0]  Pout_hs_dn   ;
reg  [N-1:0]  Pout_vs_dn   ;
reg  [N-1:0]  Pout_de_dn   ;

always@(posedge video_clk or negedge rst_n)
begin
    if(!rst_n)
        begin                          
            Pout_hs_dn  <= {N{1'b1}};
            Pout_vs_dn  <= {N{1'b1}}; 
            Pout_de_dn  <= {N{1'b0}}; 
        end
    else 
        begin                          
            Pout_hs_dn  <= {Pout_hs_dn[N-2:0],syn_off0_hs};
            Pout_vs_dn  <= {Pout_vs_dn[N-2:0],syn_off0_vs}; 
            Pout_de_dn  <= {Pout_de_dn[N-2:0],out_de}; 
        end
end


`ifdef RD_VIDEO_WIDTH_16     
    assign {lcd_b,lcd_g,lcd_r}    = off0_syn_de ? off0_syn_data[15:0] : 16'h0000;
    assign lcd_vs      			  = Pout_vs_dn[4];
    assign lcd_hs      			  = Pout_hs_dn[4];
    assign lcd_de      			  = Pout_de_dn[4];
    assign lcd_dclk    			  = video_clk;
`endif

`ifdef RD_VIDEO_WIDTH_24 
    assign {lcd_r,lcd_g,lcd_b}    = off0_syn_de ? off0_syn_data[23:0] : 24'h0000;
    assign lcd_vs      			  = Pout_vs_dn[4];
    assign lcd_hs      			  = Pout_hs_dn[4];
    assign lcd_de      			  = Pout_de_dn[4];
    assign lcd_dclk    			  = video_clk;
`endif

`ifdef RD_VIDEO_WIDTH_32 
    assign {lcd_r,lcd_g,lcd_b}    = off0_syn_de ? off0_syn_data[23:0] : 24'h0000;
    assign lcd_vs      			  = Pout_vs_dn[4];
    assign lcd_hs      			  = Pout_hs_dn[4];
    assign lcd_de      			  = Pout_de_dn[4];
    assign lcd_dclk    			  = video_clk;
`endif

DDR3MI DDR3_Memory_Interface_Top_inst 
(
    .clk                (video_clk          ),
    .memory_clk         (memory_clk         ),
    .pll_lock           (pll_lock           ),
    .rst_n              (rst_n              ),
    .app_burst_number   (app_burst_number   ),
    .cmd_ready          (cmd_ready          ),
    .cmd                (cmd                ),
    .cmd_en             (cmd_en             ),
    .addr               (addr               ),
    .wr_data_rdy        (wr_data_rdy        ),
    .wr_data            (wr_data            ),
    .wr_data_en         (wr_data_en         ),
    .wr_data_end        (wr_data_end        ),
    .wr_data_mask       (wr_data_mask       ),
    .rd_data            (rd_data            ),
    .rd_data_valid      (rd_data_valid      ),
    .rd_data_end        (rd_data_end        ),
    .sr_req             (1'b0               ),
    .ref_req            (1'b0               ),
    .sr_ack             (                   ),
    .ref_ack            (                   ),
    .init_calib_complete(init_calib_complete),
    .clk_out            (dma_clk            ),
    .burst              (1'b1               ),
    .ddr_rst            (                 ),
    .O_ddr_addr         (ddr_addr         ),
    .O_ddr_ba           (ddr_bank         ),
    .O_ddr_cs_n         (ddr_cs         ),
    .O_ddr_ras_n        (ddr_ras        ),
    .O_ddr_cas_n        (ddr_cas        ),
    .O_ddr_we_n         (ddr_we         ),
    .O_ddr_clk          (ddr_ck          ),
    .O_ddr_clk_n        (ddr_ck_n        ),
    .O_ddr_cke          (ddr_cke          ),
    .O_ddr_odt          (ddr_odt          ),
    .O_ddr_reset_n      (ddr_reset_n      ),
    .O_ddr_dqm          (ddr_dm           ),
    .IO_ddr_dq          (ddr_dq           ),
    .IO_ddr_dqs         (ddr_dqs          ),
    .IO_ddr_dqs_n       (ddr_dqs_n        )
);

endmodule