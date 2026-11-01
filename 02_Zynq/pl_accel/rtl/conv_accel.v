// conv_accel.v —— 卷积加速器顶层封装（v4，字地址接口，匹配 dpram 端口B）
//
// BRAM 字地址（每字 4 字节）：
//   0 CTRL/STATUS  bit0=start bit1=busy bit2=done
//   1 C_IN  2 C_OUT  3 H_IN  4 W_IN
//   5 WGT_OFF  6 IN_OFF  7 OUT_OFF  8 CYCLES
`default_nettype none

module conv_accel #(
    parameter OC_PAR   = 16,
    parameter OW_CHUNK = 8
)(
    input  wire        clk,
    input  wire        rstn,

    output wire [31:0] bram_addr,     // 字地址（32 位，高位置 0）
    output wire        bram_en,
    output wire [3:0]  bram_we,       // 字节使能
    output wire [31:0] bram_wdata,
    input  wire [31:0] bram_rdata
);

    localparam C_POLL   = 4'd0,
               C_POLLW  = 4'd1,
               C_CHK    = 4'd2,
               C_ISS    = 4'd3,
               C_ISS_W  = 4'd4,
               C_CAP    = 4'd5,
               C_GO     = 4'd6,
               C_RUN    = 4'd7,
               C_STAT   = 4'd8,
               C_STAT2  = 4'd9;

    reg [3:0]  cst;
    reg [3:0]  pidx;
    reg        eng_start;
    reg        drv_by_eng;

    reg [16:0] c_addr;
    reg        c_en, c_we;
    reg [31:0] c_wdata;

    wire [19:0] e_addr;              // 引擎用字节地址
    wire        e_en, e_we;
    wire [31:0] e_wdata;
    wire        eng_busy, eng_done;
    wire [31:0] eng_cycles;

    reg [15:0] c_in_r, c_out_r, h_in_r, w_in_r;
    reg [23:0] wgt_r, in_r, out_r;

// 仲裁（字地址 + 字节使能，32 位地址高位置 0）
    assign bram_addr  = drv_by_eng ? {15'd0, e_addr[18:2]} : {15'd0, c_addr};
    assign bram_en    = drv_by_eng ? e_en        : c_en;
    assign bram_we    = drv_by_eng ? {4{e_we}}   : {4{c_we}};
    assign bram_wdata = drv_by_eng ? e_wdata     : c_wdata;

    conv_engine #(
        .OC_PAR(OC_PAR),
        .OW_CHUNK(OW_CHUNK)
    ) u_eng (
        .clk(clk), .rstn(rstn),
        .start(eng_start),
        .c_in(c_in_r), .c_out(c_out_r), .h_in(h_in_r), .w_in(w_in_r),
        .wgt_base(wgt_r), .in_base(in_r), .out_base(out_r),
        .busy(eng_busy), .done(eng_done), .cycle_cnt(eng_cycles),
        .bram_addr(e_addr), .bram_en(e_en), .bram_we(e_we),
        .bram_wdata(e_wdata), .bram_rdata(bram_rdata)
    );

    always @(posedge clk) begin
        if (!rstn) begin
            cst <= C_POLL; pidx <= 0; eng_start <= 0; drv_by_eng <= 0;
            c_addr <= 0; c_en <= 0; c_we <= 0; c_wdata <= 0;
            c_in_r <= 0; c_out_r <= 0; h_in_r <= 0; w_in_r <= 0;
            wgt_r <= 0; in_r <= 0; out_r <= 0;
        end else begin
            c_en <= 1'b0;
            c_we <= 1'b0;
            if (cst != C_GO && cst != C_RUN) eng_start <= 1'b0;

            case (cst)
            C_POLL: begin
                drv_by_eng <= 1'b0;
                c_en   <= 1'b1;
                c_addr <= 17'd0;
                cst    <= C_POLLW;
            end
            C_POLLW: cst <= C_CHK;
            C_CHK: begin
                if (bram_rdata[0] && !bram_rdata[1]) begin
                    pidx   <= 4'd1;
                    c_en   <= 1'b1;
                    c_addr <= 17'd1;         // word 1
                    cst    <= C_ISS_W;
                end else begin
                    c_en   <= 1'b1;
                    c_addr <= 17'd0;
                    cst    <= C_POLLW;
                end
            end
            C_ISS: begin
                c_en   <= 1'b1;
                c_addr <= {13'd0, pidx};     // word pidx
                cst    <= C_ISS_W;
            end
            C_ISS_W: cst <= C_CAP;
            C_CAP: begin
                case (pidx)
                    4'd1: c_in_r  <= bram_rdata[15:0];
                    4'd2: c_out_r <= bram_rdata[15:0];
                    4'd3: h_in_r  <= bram_rdata[15:0];
                    4'd4: w_in_r  <= bram_rdata[15:0];
                    4'd5: wgt_r   <= bram_rdata[23:0];
                    4'd6: in_r    <= bram_rdata[23:0];
                    default: out_r <= bram_rdata[23:0];
                endcase
                if (pidx < 4'd7) begin
                    pidx <= pidx + 1;
                    cst  <= C_ISS;
                end else begin
                    c_we    <= 1'b1;
                    c_addr  <= 17'd0;
                    c_wdata <= 32'h2;
                    cst     <= C_GO;
                end
            end
            C_GO: begin
                drv_by_eng <= 1'b1;
                eng_start  <= 1'b1;
                cst        <= C_RUN;
            end
            C_RUN: begin
                eng_start <= 1'b0;
                if (eng_done) begin
                    drv_by_eng <= 1'b0;
                    cst        <= C_STAT;
                end
            end
            C_STAT: begin
                c_we    <= 1'b1;
                c_addr  <= 17'd8;
                c_wdata <= eng_cycles;
                cst     <= C_STAT2;
            end
            C_STAT2: begin
                c_we    <= 1'b1;
                c_addr  <= 17'd0;
                c_wdata <= 32'h4;
                cst     <= C_POLL;
            end
            default: cst <= C_POLL;
            endcase
        end
    end

endmodule
`default_nettype wire
