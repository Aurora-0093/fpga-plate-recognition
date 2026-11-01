module image_process(
    input               sys_clk         ,
    input               clk             ,
    input               rst_n           ,
    input               key_in          ,
    input               pre_frame_vsync ,
    input               pre_frame_hsync ,
    input               pre_frame_de    ,
    input       [15:0]  pre_rgb         ,
    input       [10:0]  xpos            ,
    input       [10:0]  ypos            ,

    output  reg         post_frame_vsync,
    output  reg         post_frame_hsync,
    output  reg         post_frame_de   ,
    output  reg [15:0]  post_rgb        ,
    output      [3:0]   state_led       ,

    output              uart_tx
);


// 第一部分：预处理

wire                  ycbcr_vsync;
wire                  ycbcr_hsync;
wire                  ycbcr_de   ;
wire    [7:0]         img_y      ;
wire    [7:0]         img_cb     ;
wire    [7:0]         img_cr     ;

wire                  binarization_vsync;
wire                  binarization_hsync;
wire                  binarization_de   ;
wire                  binarization_bit  ;
wire                  erosion_vsync     ;
wire                  erosion_hsync     ;
wire                  erosion_de        ;
wire                  erosion_bit       ;
wire                  sobel_vsync       ;
wire                  sobel_hsync       ;
wire                  sobel_de          ;
wire                  sobel_bit         ;
wire                  dilation_vsync    ;
wire                  dilation_hsync    ;
wire                  dilation_de       ;
wire                  dilation_bit      ;
wire                  projection_vsync  ;
wire                  projection_hsync  ;
wire                  projection_de     ;
wire                  projection_bit    ;
wire [9:0]            max_line_up       ;
wire [9:0]            max_line_down     ;
wire [9:0]            max_line_left     ;
wire [9:0]            max_line_right    ;

rgb2ycbcr rgb2ycbcr_inst(
    .clk             (clk             ),
    .rst_n           (rst_n           ),
    .pre_frame_vsync (pre_frame_vsync ),
    .pre_frame_hsync (pre_frame_hsync ),
    .pre_frame_de    (pre_frame_de    ),
    .img_red         (pre_rgb[15:11]  ),
    .img_green       (pre_rgb[10:5]   ),
    .img_blue        (pre_rgb[ 4:0]   ),
    .post_frame_vsync(ycbcr_vsync     ),
    .post_frame_hsync(ycbcr_hsync     ),
    .post_frame_de   (ycbcr_de        ),
    .img_y           (img_y           ),
    .img_cb          (img_cb          ),
    .img_cr          (img_cr          )
);


// 三色判据

wire is_blue_strict   = (img_cb > 8'd145) && (img_cr < 8'd128) && (img_y > 8'd35);

wire is_yellow_strict = (img_cr > 8'd136) && (img_cb < 8'd114) && (img_y > 8'd60);

wire [8:0] green_sum = img_cb + img_cr;

wire is_green_strict  = (img_cb > 8'd50 ) && (img_cb < 8'd124) &&
                        (img_cr > 8'd50 ) && (img_cr < 8'd118) &&
                        (green_sum < 9'd240) &&
                        (img_y  > 8'd40 );

wire plate_color_mask = is_blue_strict | is_yellow_strict | is_green_strict;

wire [7:0] mixed_color_feature = (plate_color_mask && in_roi_gate) ? 8'd255 : 8'd0;

reg [7:0] mixed_color_feature_r;
reg       ycbcr_vsync_r, ycbcr_hsync_r, ycbcr_de_r;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        mixed_color_feature_r <= 8'd0;
        ycbcr_vsync_r <= 1'b1;
        ycbcr_hsync_r <= 1'b0;
        ycbcr_de_r    <= 1'b0;
    end else begin
        mixed_color_feature_r <= mixed_color_feature;
        ycbcr_vsync_r <= ycbcr_vsync;
        ycbcr_hsync_r <= ycbcr_hsync;
        ycbcr_de_r    <= ycbcr_de;
    end
end

binarization binarization_inst(
    .clk                (clk                  ),
    .rst_n              (rst_n                ),
    .per_frame_vsync    (ycbcr_vsync_r        ),
    .per_frame_href     (ycbcr_hsync_r        ),
    .per_frame_clken    (ycbcr_de_r           ),
    .per_img_Y          (mixed_color_feature_r),
    .post_frame_vsync   (binarization_vsync   ),
    .post_frame_href    (binarization_hsync   ),
    .post_frame_clken   (binarization_de      ),
    .post_img_Bit       (binarization_bit     ),
    .Binary_Threshold   (8'd140               )
);

VIP_Bit_Erosion_Detector #(
    .IMG_HDISP (10'd480),
    .IMG_VDISP (10'd272)
) VIP_Bit_Erosion_Detector_u1(
    .clk              (clk                ),
    .rst_n            (rst_n              ),
    .per_frame_vsync  (binarization_vsync ),
    .per_frame_href   (binarization_hsync ),
    .per_frame_clken  (binarization_de    ),
    .per_img_Bit      (binarization_bit   ),
    .post_frame_vsync (erosion_vsync      ),
    .post_frame_href  (erosion_hsync      ),
    .post_frame_clken (erosion_de         ),
    .post_img_Bit     (erosion_bit        )
);

Sobel_Edge_Detector #(
    .SOBEL_THRESHOLD  (8'd128)
) Sobel_Edge_Detector_inst (
    .clk              (clk              ),
    .rst_n            (rst_n            ),
    .per_frame_vsync  (erosion_vsync    ),
    .per_frame_href   (erosion_hsync    ),
    .per_frame_clken  (erosion_de       ),
    .per_img_y        ({8{erosion_bit}} ),
    .post_frame_vsync (sobel_vsync      ),
    .post_frame_href  (sobel_hsync      ),
    .post_frame_clken (sobel_de         ),
    .post_img_bit     (sobel_bit        )
);

VIP_Bit_Dilation_Detector #(
    .IMG_HDISP (10'd480),
    .IMG_VDISP (10'd272)
) VIP_Bit_Dilation_Detector_u1(
    .clk              (clk            ),
    .rst_n            (rst_n          ),
    .per_frame_vsync  (sobel_vsync    ),
    .per_frame_href   (sobel_hsync    ),
    .per_frame_clken  (sobel_de       ),
    .per_img_Bit      (sobel_bit      ),
    .post_frame_vsync (dilation_vsync ),
    .post_frame_href  (dilation_hsync ),
    .post_frame_clken (dilation_de    ),
    .post_img_Bit     (dilation_bit   )
);

VIP_horizon_projection #(
    .IMG_HDISP (10'd480),
    .IMG_VDISP (10'd272)
) VIP_horizon_projection_inst(
    .clk              (clk              ),
    .rst_n            (rst_n            ),
    .per_frame_vsync  (dilation_vsync   ),
    .per_frame_href   (dilation_hsync   ),
    .per_frame_clken  (dilation_de      ),
    .per_img_Bit      (dilation_bit     ),
    .post_frame_vsync (projection_vsync ),
    .post_frame_href  (projection_hsync ),
    .post_frame_clken (projection_de    ),
    .post_img_Bit     (projection_bit   ),
    .max_line_up      (max_line_up      ),
    .max_line_down    (max_line_down    ),
    .horizon_start    (10'd10           ),
    .horizon_end      (10'd470          )
);

VIP_vertical_projection #(
    .IMG_HDISP (10'd480),
    .IMG_VDISP (10'd272)
) VIP_vertical_projection_inst(
    .clk              (clk            ),
    .rst_n            (rst_n          ),
    .per_frame_vsync  (dilation_vsync ),
    .per_frame_href   (dilation_hsync ),
    .per_frame_clken  (dilation_de    ),
    .per_img_Bit      (dilation_bit   ),
    .post_frame_vsync (               ),
    .post_frame_href  (               ),
    .post_frame_clken (               ),
    .post_img_Bit     (               ),
    .max_line_left    (max_line_left  ),
    .max_line_right   (max_line_right ),
    .vertical_start   (10'd10         ),
    .vertical_end     (10'd262        )
);


// 第二部分：定位 + 抗干扰 + 框稳定

wire [15:0] gray_rgb565 = {img_y[7:3], img_y[7:2], img_y[7:3]};
wire [7:0]  gray_val    = img_y;

parameter KEY_ACTIVE_LOW = 1'b1;

localparam USE_ASPECT     = 1'b1;
localparam USE_ROI        = 1'b0;
localparam USE_JUMP_GUARD = 1'b1;

localparam [9:0] BOX_SHRINK_X = 10'd10;
localparam [9:0] BOX_SHRINK_Y = 10'd2;

localparam [10:0] LOC_MIN_W = 11'd20;
localparam [10:0] LOC_MIN_H = 11'd8;
localparam [10:0] LOC_MAX_W = 11'd480;
localparam [10:0] LOC_MAX_H = 11'd272;

localparam [10:0] LOC_DROP_W = 11'd12;
localparam [10:0] LOC_DROP_H = 11'd6;

localparam [10:0] LOC_SHRINK = 11'd2;

localparam [9:0]  BOX_JUMP_TOL = 10'd60;

localparam [9:0] BOX_DEADBAND     = 10'd3;
localparam [3:0] BOX_SMOOTH_SHIFT = 4'd2;

// 单目测距参数
localparam [23:0] FOCAL_PX   = 24'd310;   
localparam [23:0] PLATE_W_MM = 24'd215;   
localparam [10:0] W_OFFSET   = 11'd41;    
localparam [15:0] D_SUB      = 16'd10;    

// 调试开关：0 = 不用测距（固定 149mm），1 = 用实时测距
localparam USE_REAL_DIST = 1'b1;
localparam [15:0] DIST_FALLBACK = 16'd149;

wire [9:0] fixed_left  = 10'd176;
wire [9:0] fixed_right = 10'd303;
wire [9:0] fixed_up    = 10'd120;
wire [9:0] fixed_down  = 10'd151;

reg        prev_vsync;
reg        loc_ok;
reg  [9:0] disp_left, disp_right, disp_up, disp_down;

wire        frame_start = prev_vsync && !ycbcr_vsync;

wire [9:0] p_left_raw  = (max_line_left  < max_line_right) ? max_line_left  : max_line_right;
wire [9:0] p_right_raw = (max_line_left  < max_line_right) ? max_line_right : max_line_left;
wire [9:0] p_up_raw    = (max_line_up    < max_line_down ) ? max_line_up    : max_line_down;
wire [9:0] p_down_raw  = (max_line_up    < max_line_down ) ? max_line_down  : max_line_up;

wire [10:0] p_w = {1'b0, p_right_raw} - {1'b0, p_left_raw} + 11'd1;
wire [10:0] p_h = {1'b0, p_down_raw}  - {1'b0, p_up_raw}   + 11'd1;

wire [15:0] asp_w10 = {5'd0, p_w} * 16'd10;
wire [15:0] asp_h20 = {5'd0, p_h} * 16'd20;
wire [15:0] asp_h50 = {5'd0, p_h} * 16'd50;
wire        asp_ok  = !USE_ASPECT || ((asp_w10 >= asp_h20) && (asp_w10 <= asp_h50));

wire loc_valid = (p_left_raw < p_right_raw) && (p_up_raw < p_down_raw) &&
                 (p_w >= LOC_MIN_W) && (p_w <= LOC_MAX_W) &&
                 (p_h >= LOC_MIN_H) && (p_h <= LOC_MAX_H) && asp_ok;

wire loc_dead  = (p_left_raw >= p_right_raw) || (p_up_raw >= p_down_raw) ||
                 (p_w < LOC_DROP_W) || (p_h < LOC_DROP_H);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        loc_ok <= 1'b0;
    else if (frame_start)
        loc_ok <= loc_valid | (loc_ok & ~loc_dead);
end

localparam [1:0] ROI_MISS_MAX = 2'd1;

reg [1:0] roi_miss;
reg       roi_full;

wire [10:0] disp_w = {1'b0, disp_right} - {1'b0, disp_left} + 11'd1;
wire [10:0] disp_h = {1'b0, disp_down}  - {1'b0, disp_up}   + 11'd1;
wire [10:0] roi_hw = disp_w >> 1;
wire [10:0] roi_hh = disp_h >> 1;

wire signed [11:0] rl_s = $signed({1'b0, disp_left})  - $signed({1'b0, roi_hw});
wire signed [11:0] rr_s = $signed({1'b0, disp_right}) + $signed({1'b0, roi_hw});
wire signed [11:0] ru_s = $signed({1'b0, disp_up})    - $signed({1'b0, roi_hh});
wire signed [11:0] rd_s = $signed({1'b0, disp_down})  + $signed({1'b0, roi_hh});

wire [9:0] roi_left  = (rl_s < 12'sd0)   ? 10'd0   : rl_s[9:0];
wire [9:0] roi_right = (rr_s > 12'sd479) ? 10'd479 : rr_s[9:0];
wire [9:0] roi_up    = (ru_s < 12'sd0)   ? 10'd0   : ru_s[9:0];
wire [9:0] roi_down  = (rd_s > 12'sd271) ? 10'd271 : rd_s[9:0];

wire in_roi = (x_cnt >= roi_left ) && (x_cnt <= roi_right) &&
              (y_cnt >= roi_up   ) && (y_cnt <= roi_down );

wire in_roi_gate = !USE_ROI || roi_full || in_roi;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        roi_miss <= 2'd0;
        roi_full <= 1'b1;
    end else if (frame_start) begin
        if (loc_valid) begin
            roi_miss <= 2'd0;
            roi_full <= 1'b0;
        end else if (roi_miss == ROI_MISS_MAX) begin
            roi_full <= 1'b1;
        end else begin
            roi_miss <= roi_miss + 1'b1;
        end
    end
end

reg [2:0] far_cnt;

wire [10:0] dlt_x = (m_left_pre > disp_left) ? ({1'b0, m_left_pre} - {1'b0, disp_left})
                                             : ({1'b0, disp_left}   - {1'b0, m_left_pre});
wire [10:0] dlt_y = (m_up_pre   > disp_up  ) ? ({1'b0, m_up_pre}   - {1'b0, disp_up  })
                                             : ({1'b0, disp_up}     - {1'b0, m_up_pre  });
wire        far_jump = (dlt_x > {1'b0, BOX_JUMP_TOL}) || (dlt_y > {1'b0, BOX_JUMP_TOL});

always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        far_cnt <= 3'd0;
    else if (frame_start) begin
        if (loc_ok && far_jump)
            far_cnt <= (far_cnt == 3'd7) ? 3'd7 : far_cnt + 1'b1;
        else
            far_cnt <= 3'd0;
    end
end

wire jump_accept = !USE_JUMP_GUARD || !far_jump || (far_cnt >= 3'd2);

wire [10:0] d_left  = (p_left_raw  > LOC_SHRINK) ? ({1'b0, p_left_raw } - LOC_SHRINK) : 11'd0;
wire [10:0] d_right = (p_right_raw > LOC_SHRINK) ? ({1'b0, p_right_raw} - LOC_SHRINK) : 11'd0;
wire [10:0] d_up    = (p_up_raw    > LOC_SHRINK) ? ({1'b0, p_up_raw   } - LOC_SHRINK) : 11'd0;
wire [10:0] d_down  = (p_down_raw  > LOC_SHRINK) ? ({1'b0, p_down_raw } - LOC_SHRINK) : 11'd0;

wire [9:0] m_left  = d_left[9:0];
wire [9:0] m_right = (d_right > 11'd479) ? 10'd479 : d_right[9:0];
wire [9:0] m_up    = d_up[9:0];
wire [9:0] m_down  = (d_down  > 11'd271) ? 10'd271 : d_down[9:0];

wire [9:0] m_left_pre = m_left;
wire [9:0] m_up_pre   = m_up;

wire [10:0] m_w = {1'b0, m_right} - {1'b0, m_left} + 11'd1;
wire [10:0] m_h = {1'b0, m_down}  - {1'b0, m_up}   + 11'd1;

wire shrink_ok = (m_w > 11'd56) && (m_h > 11'd16);

wire [9:0] src_l = shrink_ok ? (m_left  + BOX_SHRINK_X) : m_left;
wire [9:0] src_r = shrink_ok ? (m_right - BOX_SHRINK_X) : m_right;
wire [9:0] src_u = shrink_ok ? (m_up    + BOX_SHRINK_Y) : m_up;
wire [9:0] src_d = shrink_ok ? (m_down  - BOX_SHRINK_Y) : m_down;

wire [10:0] center_x = {1'b0, m_left} + (m_w >> 1);
wire [10:0] center_y = {1'b0, m_up}   + (m_h >> 1);

wire [10:0] ex_l = (center_x > 11'd64 ) ? (center_x - 11'd64 ) : 11'd0;
wire [10:0] ex_u = (center_y > 11'd16 ) ? (center_y - 11'd16 ) : 11'd0;

wire [9:0] f_left  = (m_w >= 11'd128) ? m_left :
                     (ex_l > 11'd352) ? 10'd352 : ex_l[9:0];
wire [9:0] f_right = (m_w >= 11'd128) ? m_right : (f_left + 10'd127);
wire [9:0] f_up    = (m_h >= 11'd32)  ? m_up   :
                     (ex_u > 11'd240) ? 10'd240 : ex_u[9:0];
wire [9:0] f_down  = (m_h >= 11'd32)  ? m_down : (f_up + 10'd31);

wire [9:0] next_crop_left  = loc_valid ? f_left  : fixed_left;
wire [9:0] next_crop_right = loc_valid ? f_right : fixed_right;
wire [9:0] next_crop_up    = loc_valid ? f_up    : fixed_up;
wire [9:0] next_crop_down  = loc_valid ? f_down  : fixed_down;

function [9:0] med3;
    input [9:0] a;
    input [9:0] b;
    input [9:0] c;
    reg   [9:0] mn;
    reg   [9:0] mx;
    reg  [10:0] sum;
    begin
        mn  = (a < b) ? ((a < c) ? a : c) : ((b < c) ? b : c);
        mx  = (a > b) ? ((a > c) ? a : c) : ((b > c) ? b : c);
        sum = {1'b0, a} + {1'b0, b} + {1'b0, c};
        med3 = sum - {1'b0, mn} - {1'b0, mx};
    end
endfunction

function [9:0] box_smooth;
    input [9:0] cur;
    input [9:0] tgt;
    reg   [9:0] dif;
    begin
        if (tgt > cur) begin
            dif = tgt - cur;
            box_smooth = (dif > BOX_DEADBAND) ? (cur + (dif >> BOX_SMOOTH_SHIFT)) : cur;
        end else begin
            dif = cur - tgt;
            box_smooth = (dif > BOX_DEADBAND) ? (cur - (dif >> BOX_SMOOTH_SHIFT)) : cur;
        end
    end
endfunction

wire use_new = loc_ok && jump_accept;

wire [9:0] tgt_left  = use_new ? src_l : disp_left;
wire [9:0] tgt_right = use_new ? src_r : disp_right;
wire [9:0] tgt_up    = use_new ? src_u : disp_up;
wire [9:0] tgt_down  = use_new ? src_d : disp_down;

reg [9:0] tgt_left_d1 , tgt_left_d2 ;
reg [9:0] tgt_right_d1, tgt_right_d2;
reg [9:0] tgt_up_d1   , tgt_up_d2   ;
reg [9:0] tgt_down_d1 , tgt_down_d2 ;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        tgt_left_d1  <= fixed_left;  tgt_left_d2  <= fixed_left;
        tgt_right_d1 <= fixed_right; tgt_right_d2 <= fixed_right;
        tgt_up_d1    <= fixed_up;    tgt_up_d2    <= fixed_up;
        tgt_down_d1  <= fixed_down;  tgt_down_d2  <= fixed_down;
    end else if (frame_start) begin
        tgt_left_d2  <= tgt_left_d1;   tgt_left_d1  <= tgt_left;
        tgt_right_d2 <= tgt_right_d1;  tgt_right_d1 <= tgt_right;
        tgt_up_d2    <= tgt_up_d1;     tgt_up_d1    <= tgt_up;
        tgt_down_d2  <= tgt_down_d1;   tgt_down_d1  <= tgt_down;
    end
end

wire [9:0] med_left  = med3(tgt_left , tgt_left_d1 , tgt_left_d2 );
wire [9:0] med_right = med3(tgt_right, tgt_right_d1, tgt_right_d2);
wire [9:0] med_up    = med3(tgt_up   , tgt_up_d1   , tgt_up_d2   );
wire [9:0] med_down  = med3(tgt_down , tgt_down_d1 , tgt_down_d2 );

wire [9:0] nxt_left  = box_smooth(disp_left,  med_left );
wire [9:0] nxt_right = box_smooth(disp_right, med_right);
wire [9:0] nxt_up    = box_smooth(disp_up,    med_up   );
wire [9:0] nxt_down  = box_smooth(disp_down,  med_down );

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        disp_left  <= fixed_left;
        disp_right <= fixed_right;
        disp_up    <= fixed_up;
        disp_down  <= fixed_down;
    end else if (frame_start) begin
        disp_left  <= nxt_left;
        disp_right <= (nxt_right <= nxt_left) ? (nxt_left + 10'd1) : nxt_right;
        disp_up    <= nxt_up;
        disp_down  <= (nxt_down  <= nxt_up  ) ? (nxt_up   + 10'd1) : nxt_down;
    end
end


// 测距
// 像素域：每帧只锁存一次宽度并翻转标志
reg [10:0] pw_lat;
reg        wr_tog;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        pw_lat <= 11'd0;
        wr_tog <= 1'b0;
    end else if (frame_start) begin
        pw_lat <= p_w;
        wr_tog <= ~wr_tog;
    end
end

// 跨到 sys_clk 域
reg [2:0] tog_sync;
always @(posedge sys_clk or negedge rst_n) begin
    if (!rst_n) tog_sync <= 3'b000;
    else        tog_sync <= {tog_sync[1:0], wr_tog};
end

// 同步后的翻转沿，1 拍脉冲，作为除法的启动信号
wire dist_sample = tog_sync[2] ^ tog_sync[1];

// loc_ok 也同步两拍
reg [1:0] lok_sync;
always @(posedge sys_clk or negedge rst_n) begin
    if (!rst_n) lok_sync <= 2'b00;
    else        lok_sync <= {lok_sync[0], loc_ok};
end

// 除法器
wire [15:0] dist_mm;
wire        dist_ok;
wire [10:0] w_used;

plate_distance #(
    .FOCAL_PX  (FOCAL_PX   ),
    .PLATE_W_MM(PLATE_W_MM ),
    .W_OFFSET  (W_OFFSET   ),
    .D_SUB     (D_SUB      ),
    .D_MIN     (16'd150    ),
    .D_MAX     (16'd30000  )
) plate_distance_inst (
    .clk         (sys_clk   ),
    .rst_n       (rst_n     ),
    .frame_start (dist_sample),
    .loc_valid   (lok_sync[1]),
    .plate_w_px  (pw_lat    ),
    .dist_mm     (dist_mm   ),
    .dist_ok     (dist_ok   ),
    .w_used      (w_used    )
);


// 第三部分：按键触发 + 采集 + 颜色/距离判定

reg [9:0]  x_cnt, y_cnt;
reg [9:0]  crop_left, crop_right, crop_up, crop_down;
reg        key_meta, key_sync, key_sync_d;

wire       key_press = KEY_ACTIVE_LOW ? (key_sync_d && !key_sync)
                                      : (!key_sync_d && key_sync);

reg        capture_done;
reg        send_active;
reg        wait_frame;
reg [7:0]  img_bram [0:4095];
reg [9:0]  scale_x_acc;
reg [9:0]  scale_y_acc;
reg [7:0]  target_x;
reg [5:0]  target_y;
reg        row_selected;
reg [1:0]  send_active_sync;

wire       send_finished = send_active_sync[1] && !send_active_sync[0];
reg        armed;

reg [23:0] cnt_blue;
reg [23:0] cnt_yellow;
reg [23:0] cnt_green;
reg [7:0]  color_flag;
reg [15:0] dist_hold;

localparam [24:0] MIN_CNT = 25'd300;

wire [24:0] n_blue   = {1'b0, cnt_blue}   + {24'd0, is_blue_strict  };
wire [24:0] n_yellow = {1'b0, cnt_yellow} + {24'd0, is_yellow_strict};
wire [24:0] n_green  = {1'b0, cnt_green}  + {24'd0, is_green_strict };

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        key_meta <= 1'b1; key_sync <= 1'b1; key_sync_d <= 1'b1;
    end else begin
        key_meta   <= key_in;
        key_sync   <= key_meta;
        key_sync_d <= key_sync;
    end
end

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        x_cnt <= 10'd0;
        y_cnt <= 10'd0;
        crop_left  <= fixed_left;
        crop_right <= fixed_right;
        crop_up    <= fixed_up;
        crop_down  <= fixed_down;
        prev_vsync <= 1'b1;
    end else begin
        prev_vsync <= ycbcr_vsync;
        if (prev_vsync && !ycbcr_vsync) begin
            x_cnt <= 10'd0;
            y_cnt <= 10'd0;
            crop_left  <= next_crop_left;
            crop_right <= next_crop_right;
            crop_up    <= next_crop_up;
            crop_down  <= next_crop_down;
        end else if (ycbcr_de) begin
            if (x_cnt == 10'd479) begin
                x_cnt <= 10'd0;
                if (y_cnt < 10'd271) y_cnt <= y_cnt + 1'b1;
            end else begin
                x_cnt <= x_cnt + 1'b1;
            end
        end
    end
end

wire       in_crop = (x_cnt >= crop_left) && (x_cnt <= crop_right) &&
                     (y_cnt >= crop_up  ) && (y_cnt <= crop_down );
wire [9:0] crop_w  = crop_right - crop_left + 10'd1;
wire [9:0] crop_h  = crop_down  - crop_up   + 10'd1;

wire [10:0] next_x_acc = (x_cnt == crop_left) ? 11'd128
                                              : ({1'b0, scale_x_acc} + 11'd128);
wire [7:0]  x_target_base = (x_cnt == crop_left) ? 8'd0 : target_x;
wire [10:0] next_y_acc = {1'b0, scale_y_acc} + 11'd32;
wire        take_this_row = (x_cnt == crop_left) ? (next_y_acc >= {1'b0, crop_h})
                                                 : row_selected;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        scale_x_acc <= 10'd0;
        scale_y_acc <= 10'd0;
        target_x    <= 8'd0;
        target_y    <= 6'd0;
        row_selected <= 1'b0;
        capture_done <= 1'b0;
        wait_frame   <= 1'b1;
        armed        <= 1'b0;
        send_active_sync <= 2'b00;
        cnt_blue   <= 24'd0;
        cnt_yellow <= 24'd0;
        cnt_green  <= 24'd0;
        color_flag <= 8'd0;
        dist_hold  <= 16'd0;
    end else begin
        send_active_sync <= {send_active_sync[0], send_active};

        if (send_finished) begin
            capture_done <= 1'b0;
            armed        <= 1'b0;
        end

        if (key_press && !armed && !capture_done && !send_active_sync[1]) begin
            scale_x_acc  <= 10'd0;
            scale_y_acc  <= 10'd0;
            target_x     <= 8'd0;
            target_y     <= 6'd0;
            row_selected <= 1'b0;
            wait_frame   <= 1'b1;
            armed        <= 1'b1;
            cnt_blue     <= 24'd0;
            cnt_yellow   <= 24'd0;
            cnt_green    <= 24'd0;
            color_flag   <= 8'd0;
            dist_hold    <= 16'd0;
        end
        else if (armed && !capture_done && !send_active_sync[1]) begin
            if (wait_frame && ycbcr_de && x_cnt == 10'd0 && y_cnt == 10'd0)
                wait_frame <= 1'b0;

            if (!wait_frame && ycbcr_de && in_crop) begin
                if (is_blue_strict  ) cnt_blue   <= cnt_blue   + 1'b1;
                if (is_yellow_strict) cnt_yellow <= cnt_yellow + 1'b1;
                if (is_green_strict ) cnt_green  <= cnt_green  + 1'b1;

                if (x_cnt == crop_left) begin
                    scale_x_acc  <= 10'd0;
                    target_x     <= 8'd0;
                    row_selected <= (next_y_acc >= {1'b0, crop_h});
                    if (next_y_acc >= {1'b0, crop_h})
                        scale_y_acc <= next_y_acc - {1'b0, crop_h};
                    else
                        scale_y_acc <= next_y_acc[9:0];
                end

                if (take_this_row && crop_w >= 10'd128) begin
                    if (next_x_acc >= {1'b0, crop_w}) begin
                        scale_x_acc <= next_x_acc - {1'b0, crop_w};
                        if (x_target_base < 8'd128 && target_y < 6'd32) begin
                            img_bram[{target_y[4:0], x_target_base[6:0]}] <= gray_val;
                            target_x <= x_target_base + 1'b1;
                        end
                    end else begin
                        scale_x_acc <= next_x_acc[9:0];
                    end
                end

                if (x_cnt == crop_right && row_selected) begin
                    if (target_y < 6'd32) target_y <= target_y + 1'b1;
                end

                if (x_cnt == crop_right && y_cnt == crop_down) begin
                    capture_done <= 1'b1;
                    // 距离用 plate_distance 在本帧 vsync 算出的值，无效帧存 0
                    dist_hold <= USE_REAL_DIST ? (dist_ok ? dist_mm : 16'd0)
                                               : DIST_FALLBACK;

                    if (n_green > MIN_CNT && n_green >= n_yellow && n_green >= n_blue)
                        color_flag <= 8'd3;
                    else if (n_yellow > MIN_CNT && n_yellow >= n_blue)
                        color_flag <= 8'd1;
                    else if (n_blue > MIN_CNT)
                        color_flag <= 8'd2;
                    else
                        color_flag <= 8'd0;
                end
            end
        end
    end
end


// 第四部分：UART（4103 字节）

localparam BAUD_DIV    = 117;    
                                 
localparam FRAME_BYTES = 4103;

reg  [15:0] baud_cnt;
reg  [3:0]  bit_cnt;
reg  [1:0]  tx_state;
reg  [7:0]  tx_data;
reg  [11:0] send_addr;
reg  [12:0] send_byte_cnt;
reg         uart_tx_reg;
reg  [1:0]  done_sync;

wire        done_rise = done_sync[0] && !done_sync[1];

wire [7:0] uart_payload = (send_byte_cnt < 13'd2)
                        ? ((send_byte_cnt == 13'd0) ? 8'hAA : 8'h55)
                        : (send_byte_cnt < 13'd4098)
                        ? img_bram[send_addr]
                        : (send_byte_cnt == 13'd4098) ? color_flag
                        : (send_byte_cnt == 13'd4099) ? dist_hold[15:8]
                        : (send_byte_cnt == 13'd4100) ? dist_hold[7:0]
                        : (send_byte_cnt == 13'd4101) ? 8'h0D
                        : 8'h0A;

always @(posedge sys_clk or negedge rst_n) begin
    if (!rst_n) done_sync <= 2'b00;
    else        done_sync <= {done_sync[0], capture_done};
end

localparam S_IDLE  = 2'd0;
localparam S_START = 2'd1;
localparam S_DATA  = 2'd2;
localparam S_STOP  = 2'd3;

always @(posedge sys_clk or negedge rst_n) begin
    if (!rst_n) begin
        tx_state      <= S_IDLE;
        baud_cnt      <= 16'd0;
        bit_cnt       <= 4'd0;
        tx_data       <= 8'd0;
        send_addr     <= 12'd0;
        send_byte_cnt <= 13'd0;
        send_active   <= 1'b0;
        uart_tx_reg   <= 1'b1;
    end else begin
        case (tx_state)
            S_IDLE: begin
                uart_tx_reg <= 1'b1;
                if (done_rise && !send_active) begin
                    send_active   <= 1'b1;
                    send_addr     <= 12'd0;
                    send_byte_cnt <= 13'd0;
                    tx_data       <= 8'hAA;
                    baud_cnt      <= 16'd0;
                    bit_cnt       <= 4'd0;
                    tx_state      <= S_START;
                end else if (send_active) begin
                    tx_data  <= uart_payload;
                    baud_cnt <= 16'd0;
                    bit_cnt  <= 4'd0;
                    tx_state <= S_START;
                end
            end

            S_START: begin
                uart_tx_reg <= 1'b0;
                if (baud_cnt == BAUD_DIV-1) begin
                    baud_cnt <= 16'd0;
                    tx_state <= S_DATA;
                end else begin
                    baud_cnt <= baud_cnt + 1'b1;
                end
            end

            S_DATA: begin
                uart_tx_reg <= tx_data[bit_cnt];
                if (baud_cnt == BAUD_DIV-1) begin
                    baud_cnt <= 16'd0;
                    if (bit_cnt == 4'd7) tx_state <= S_STOP;
                    else                 bit_cnt  <= bit_cnt + 1'b1;
                end else begin
                    baud_cnt <= baud_cnt + 1'b1;
                end
            end

            S_STOP: begin
                uart_tx_reg <= 1'b1;
                if (baud_cnt == BAUD_DIV-1) begin
                    baud_cnt <= 16'd0;
                    if (send_byte_cnt == FRAME_BYTES-1) begin
                        send_active <= 1'b0;
                        tx_state    <= S_IDLE;
                    end else begin
                        send_byte_cnt <= send_byte_cnt + 1'b1;
                        if (send_byte_cnt >= 13'd2 && send_byte_cnt < 13'd4097)
                            send_addr <= send_addr + 1'b1;
                        tx_state <= S_IDLE;
                    end
                end else begin
                    baud_cnt <= baud_cnt + 1'b1;
                end
            end

            default: tx_state <= S_IDLE;
        endcase
    end
end


// 第五部分：LCD 输出（打一拍寄存器 + 可选彩条）

// 0 = 正常显示   1 = 彩条（用来判断是屏/时序问题还是图像问题）
localparam TEST_PATTERN = 1'b0;

wire [15:0] pre_rgb_swapped = {pre_rgb[4:0], pre_rgb[10:5], pre_rgb[15:11]};

localparam [15:0] C_RED   = 16'h001F;
localparam [15:0] C_BLUE  = 16'hF800;
localparam [15:0] C_GREEN = 16'h07E0;
localparam [15:0] C_YELLOW= 16'h07FF;   // 低5位红 + 中间绿色
localparam [15:0] C_WHITE = 16'hFFFF;
localparam [15:0] C_BLACK = 16'h0000;
localparam [15:0] C_GRAY  = 16'h7BEF;

localparam [15:0] BORDER_COLOR = C_RED;
localparam [9:0]  BORDER_W     = 10'd4;

wire box_up    = (y_cnt >= disp_up  ) && (y_cnt <  disp_up  + BORDER_W) &&
                 (x_cnt >= disp_left) && (x_cnt <= disp_right);
wire box_down  = (y_cnt <= disp_down) && (y_cnt >  disp_down- BORDER_W) &&
                 (x_cnt >= disp_left) && (x_cnt <= disp_right);
wire box_left  = (x_cnt >= disp_left) && (x_cnt <  disp_left+ BORDER_W) &&
                 (y_cnt >= disp_up  ) && (y_cnt <= disp_down );
wire box_right = (x_cnt <= disp_right)&& (x_cnt >  disp_right-BORDER_W) &&
                 (y_cnt >= disp_up  ) && (y_cnt <= disp_down );

wire box_border = box_up | box_down | box_left | box_right;

// 彩条：每 60 像素一条
reg [15:0] bar_rgb;
always @(*) begin
    if      (x_cnt < 10'd60 ) bar_rgb = C_WHITE;
    else if (x_cnt < 10'd120) bar_rgb = C_YELLOW;
    else if (x_cnt < 10'd180) bar_rgb = C_GREEN;
    else if (x_cnt < 10'd240) bar_rgb = C_RED;
    else if (x_cnt < 10'd300) bar_rgb = C_BLUE;
    else if (x_cnt < 10'd360) bar_rgb = C_BLACK;
    else if (x_cnt < 10'd420) bar_rgb = C_GRAY;
    else                      bar_rgb = C_WHITE;
end

wire [15:0] rgb_mux = TEST_PATTERN
                    ? bar_rgb
                    : (box_border ? BORDER_COLOR : pre_rgb_swapped);

// 输出统一打一拍：数据、行场、DE 一起延后，相对关系不变
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        post_frame_vsync <= 1'b1;
        post_frame_hsync <= 1'b0;
        post_frame_de    <= 1'b0;
        post_rgb         <= 16'd0;
    end else begin
        post_frame_vsync <= ycbcr_vsync;
        post_frame_hsync <= ycbcr_hsync;
        post_frame_de    <= ycbcr_de;
        post_rgb         <= rgb_mux;
    end
end

assign state_led = ~{send_active_sync[1], capture_done, loc_valid, armed};
assign uart_tx   = uart_tx_reg;

endmodule


// 单目测距

module plate_distance #(
    parameter [23:0] FOCAL_PX   = 24'd310,
    parameter [23:0] PLATE_W_MM = 24'd215,
    parameter [10:0] W_OFFSET   = 11'd41,
    parameter [15:0] D_SUB      = 16'd10,
    parameter [15:0] D_MIN      = 16'd150,
    parameter [15:0] D_MAX      = 16'd30000
)(
    input             clk,
    input             rst_n,
    input             frame_start,
    input             loc_valid,
    input      [10:0] plate_w_px,
    output reg [15:0] dist_mm,
    output reg        dist_ok,
    output reg [10:0] w_used
);

wire [31:0] numer = FOCAL_PX * PLATE_W_MM;

function [10:0] med3_11;
    input [10:0] a;
    input [10:0] b;
    input [10:0] c;
    reg   [10:0] mn;
    reg   [10:0] mx;
    reg   [11:0] sum;
    begin
        mn  = (a < b) ? ((a < c) ? a : c) : ((b < c) ? b : c);
        mx  = (a > b) ? ((a > c) ? a : c) : ((b > c) ? b : c);
        sum = {1'b0, a} + {1'b0, b} + {1'b0, c};
        med3_11 = sum - {1'b0, mn} - {1'b0, mx};
    end
endfunction

reg [10:0] w_d1, w_d2;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        w_d1 <= 11'd0;
        w_d2 <= 11'd0;
    end else if (frame_start) begin
        w_d2 <= w_d1;
        w_d1 <= plate_w_px;
    end
end

wire [10:0] w_med = med3_11(plate_w_px, w_d1, w_d2);
wire [10:0] w_net = (w_med > W_OFFSET) ? (w_med - W_OFFSET) : 11'd0;

localparam S_IDLE = 2'd0;
localparam S_DIV  = 2'd1;
localparam S_FIN  = 2'd2;

reg [1:0]  state;
reg [5:0]  bit_cnt;
reg [31:0] num;
reg [31:0] quo;
reg [31:0] rem;
reg [10:0] dvs;

wire [32:0] rem_sh  = {rem, num[31]};
wire [32:0] dvs_ext = {22'd0, dvs};
wire        ge      = (rem_sh >= dvs_ext);
wire [32:0] rem_nx  = ge ? (rem_sh - dvs_ext) : rem_sh;

wire [31:0] dist_sum = (quo > {16'd0, D_SUB}) ? (quo - {16'd0, D_SUB}) : 32'd0;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state   <= S_IDLE;
        bit_cnt <= 6'd0;
        num     <= 32'd0;
        quo     <= 32'd0;
        rem     <= 32'd0;
        dvs     <= 11'd0;
        dist_mm <= 16'd0;
        dist_ok <= 1'b0;
        w_used  <= 11'd0;
    end else begin
        case (state)
            S_IDLE: begin
                if (frame_start) begin
                    if (loc_valid && w_net >= 11'd16) begin
                        num     <= numer;
                        dvs     <= w_net;
                        w_used  <= w_med;
                        quo     <= 32'd0;
                        rem     <= 32'd0;
                        bit_cnt <= 6'd32;
                        dist_ok <= 1'b0;
                        state   <= S_DIV;
                    end else begin
                        dist_ok <= 1'b0;
                    end
                end
            end

            S_DIV: begin
                rem     <= rem_nx[31:0];
                num     <= {num[30:0], 1'b0};
                quo     <= {quo[30:0], ge};
                bit_cnt <= bit_cnt - 1'b1;
                if (bit_cnt == 6'd1) state <= S_FIN;
            end

            S_FIN: begin
                if (dist_sum == 32'd0)
                    dist_ok <= 1'b0;
                else if (dist_sum < {16'd0, D_MIN})
                    dist_ok <= 1'b0;
                else if (dist_sum > {16'd0, D_MAX})
                    dist_ok <= 1'b0;
                else begin
                    dist_mm <= dist_sum[15:0];
                    dist_ok <= 1'b1;
                end
                state <= S_IDLE;
            end

            default: state <= S_IDLE;
        endcase
    end
end

endmodule