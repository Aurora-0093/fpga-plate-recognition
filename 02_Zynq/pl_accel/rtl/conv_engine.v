// conv_engine.v —— 3x3 / pad=1 / stride=1 卷积加速引擎（v3，最终结构）
//
//   out[oc][oh][ow] = sum(ic,kh,kw) in[ic][oh+kh-1][ow+kw-1] * wblk[...]
//
//   * 输入 uint8、权重 int8、累加 int32
//   * 16 个输出通道并行（每周期 16 次乘加）
//   * 只做卷积；ReLU / 量化 / 池化 由 ARM 做
//
// 权重布局（16 通道打包，ARM 开机重排一次）：
//   wblk[ ((ocb*C_IN + ic)*9 + kh*3 + kw)*16 + lane ]   oc = ocb*16 + lane
//
// BRAM 字节地址：
//   权重  wgt_base + 上式
//   输入  in_base  + (ic*H_IN + ih)*W_IN + iw
//   输出  out_base + ((oc*H_OUT + oh)*W_OUT + ow)*4
`default_nettype none

module conv_engine #(
    parameter OC_PAR   = 16,
    parameter OW_CHUNK = 32
)(
    input  wire        clk,
    input  wire        rstn,

    input  wire        start,
    input  wire [15:0] c_in,
    input  wire [15:0] c_out,
    input  wire [15:0] h_in,
    input  wire [15:0] w_in,
    input  wire [23:0] wgt_base,
    input  wire [23:0] in_base,
    input  wire [23:0] out_base,

    output reg         busy,
    output reg         done,
    output reg  [31:0] cycle_cnt,

    output reg  [19:0] bram_addr,
    output reg         bram_en,
    output reg         bram_we,
    output reg  [31:0] bram_wdata,
    input  wire [31:0] bram_rdata
);

    localparam S_IDLE  = 4'd0,
               S_CLEAR = 4'd1,
               S_WADDR = 4'd2,
               S_WDATA = 4'd3,
               S_PADDR = 4'd4,
               S_PDATA = 4'd5,
               S_PNEXT = 4'd6,
               S_OADDR = 4'd7,
               S_FIN   = 4'd8,
               S_WWAIT = 4'd9,
               S_PWAIT = 4'd10;

    reg [3:0] st;

    // 循环变量
    reg [15:0] row, ocb, owc, ic, kh, kw, ow;
    reg [3:0]  lane;
    reg [1:0]  wcnt;

    reg signed [31:0] acc [0:OC_PAR*OW_CHUNK-1];
    reg [7:0]         wbuf [0:OC_PAR-1];

    wire [15:0] h_out = h_in;
    wire [15:0] w_out = w_in;

    wire [15:0] ow_base   = owc * OW_CHUNK;
    wire [15:0] chunk_len = (ow_base + OW_CHUNK > w_out) ? (w_out - ow_base) : OW_CHUNK;
    wire [15:0] n_owc     = (w_out + OW_CHUNK - 1) / OW_CHUNK;
    wire [15:0] n_ocb     = (c_out + OC_PAR - 1) / OC_PAR;
    wire [15:0] n_lane    = ((c_out - ocb * OC_PAR) > OC_PAR) ? OC_PAR : (c_out - ocb * OC_PAR);

    // 输入坐标（含 padding）
    wire signed [17:0] ih_s = $signed({2'b00, row}) + $signed({16'b0, kh}) - 18'sd1;
    wire signed [17:0] iw_s = $signed({2'b00, ow_base + ow}) + $signed({16'b0, kw}) - 18'sd1;
    wire               in_ok = (ih_s >= 0) && (ih_s < $signed({2'b00, h_in}))
                            && (iw_s >= 0) && (iw_s < $signed({2'b00, w_in}));

    wire [31:0] in_byte_addr = in_base + (ic * h_in + ih_s[15:0]) * w_in + iw_s[15:0];
    wire [31:0] wgt_byte_addr = wgt_base + ((((ocb * c_in + ic) * 9 + kh * 3 + kw)) << 4);
    wire [31:0] out_byte_addr = out_base
                              + ((((ocb * OC_PAR) * h_out + row) * w_out + ow_base) << 2);

    wire [1:0] in_sel = in_byte_addr[1:0];

    // 按 in_sel 从 bram_rdata 取字节
    reg [7:0] in_word_byte;
    always @(*) begin
        case (in_sel)
            2'd0: in_word_byte = bram_rdata[7:0];
            2'd1: in_word_byte = bram_rdata[15:8];
            2'd2: in_word_byte = bram_rdata[23:16];
            default: in_word_byte = bram_rdata[31:24];
        endcase
    end

    integer i;

    always @(posedge clk) begin
        if (!rstn) begin
            st <= S_IDLE; busy <= 0; done <= 0; cycle_cnt <= 0;
            bram_en <= 0; bram_we <= 0; bram_addr <= 0; bram_wdata <= 0;
            row <= 0; ocb <= 0; owc <= 0; ic <= 0; kh <= 0; kw <= 0; ow <= 0; wcnt <= 0; lane <= 0;
            for (i = 0; i < OC_PAR*OW_CHUNK; i = i + 1) acc[i] <= 0;
            for (i = 0; i < OC_PAR; i = i + 1) wbuf[i] <= 0;
        end else begin
            bram_en <= 1'b0;
            bram_we <= 1'b0;
            if (busy) cycle_cnt <= cycle_cnt + 1;

            case (st)
            S_IDLE: begin
                done <= 1'b0;
                if (start) begin
                    busy <= 1'b1;
                    cycle_cnt <= 0;
                    row <= 0; ocb <= 0; owc <= 0;
                    st <= S_CLEAR;
                end
            end
            S_CLEAR: begin
                for (i = 0; i < OC_PAR*OW_CHUNK; i = i + 1) acc[i] <= 0;
                ic <= 0; kh <= 0; kw <= 0; ow <= 0; wcnt <= 0; lane <= 0;
                st <= S_WADDR;
            end
            // 读第 wcnt 个权重字（4 字节 = 4 个通道的权重）
            S_WADDR: begin
                bram_en   <= 1'b1;
                bram_addr <= (wgt_byte_addr[19:2] + {18'd0, wcnt}) << 2;
                st <= S_WWAIT;
            end
            S_WWAIT: begin            // BRAM 读延迟 1 拍，等数据有效
                st <= S_WDATA;
            end
            S_WDATA: begin
                wbuf[wcnt*4+0] <= bram_rdata[7:0];
                wbuf[wcnt*4+1] <= bram_rdata[15:8];
                wbuf[wcnt*4+2] <= bram_rdata[23:16];
                wbuf[wcnt*4+3] <= bram_rdata[31:24];
                if (wcnt == 2'd3) begin
                    wcnt <= 0;
                    ow   <= 0;
                    st   <= S_PADDR;
                end else begin
                    wcnt <= wcnt + 1;
                    st   <= S_WADDR;
                end
            end
            S_PADDR: begin
                if (!in_ok) begin              // padding，跳过
                    st <= S_PNEXT;
                end else begin
                    bram_en   <= 1'b1;
                    bram_addr <= {in_byte_addr[19:2], 2'b00};
                    st <= S_PWAIT;
                end
            end
            S_PWAIT: begin            // BRAM 读延迟 1 拍
                st <= S_PDATA;
            end
            S_PDATA: begin
                for (i = 0; i < OC_PAR; i = i + 1) begin
                    if (i < n_lane)
                        acc[i*OW_CHUNK + ow] <= acc[i*OW_CHUNK + ow]
                                              + $signed({24'b0, in_word_byte})
                                              * $signed({{24{wbuf[i][7]}}, wbuf[i]});
                end
                st <= S_PNEXT;
            end
            S_PNEXT: begin
                if (ow + 1 < chunk_len) begin
                    ow <= ow + 1;
                    st <= S_PADDR;
                end else begin
                    ow <= 0;
                    if (kw != 2) begin
                        kw <= kw + 1; st <= S_WADDR;            // kw 变 -> 权重要重读
                    end else if (kh != 2) begin
                        kw <= 0; kh <= kh + 1; st <= S_WADDR;   // kh 变 -> 重读
                    end else if (ic + 1 < c_in) begin
                        kw <= 0; kh <= 0; ic <= ic + 1; st <= S_WADDR;  // ic 变 -> 重读
                    end else begin
                        kw <= 0; kh <= 0; ic <= 0; wcnt <= 0; ow <= 0; lane <= 0;
                        st <= S_OADDR;
                    end
                end
            end
            // 写回：每个周期写 1 个 int32（lane 外层，ow 内层，共 16*chunk_len 次）
            S_OADDR: begin
                bram_we    <= 1'b1;
                bram_addr  <= {out_byte_addr[19:2], 2'b00}
                            + ((lane * (h_out * w_out) + ow) << 2);
                bram_wdata <= acc[lane*OW_CHUNK + ow];
                if (ow + 1 < chunk_len) begin
                    ow <= ow + 1;
                end else begin
                    ow <= 0;
                    if (lane + 1 >= n_lane) begin
                        lane <= 0;
                        st   <= S_FIN;
                    end else begin
                        lane <= lane + 1;
                    end
                end
            end
            S_FIN: begin
                if (owc + 1 < n_owc) begin
                    owc <= owc + 1; st <= S_CLEAR;
                end else if (ocb + 1 < n_ocb) begin
                    owc <= 0; ocb <= ocb + 1; st <= S_CLEAR;
                end else if (row + 1 < h_out) begin
                    owc <= 0; ocb <= 0; row <= row + 1; st <= S_CLEAR;
                end else begin
                    busy <= 1'b0; done <= 1'b1; st <= S_IDLE;
                end
            end
            default: st <= S_IDLE;
            endcase
        end
    end

endmodule
`default_nettype wire
