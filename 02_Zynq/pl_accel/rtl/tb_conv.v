// tb_conv.v —— conv_engine 仿真台
//   内存布局（字节地址）：
//     0x00000 权重（打包布局）
//     0x10000 输入特征图
//     0x20000 输出（int32）
`timescale 1ns/1ps

module tb_conv;

    localparam C_IN  = 4;
    localparam C_OUT = 32;
    localparam H     = 8;
    localparam W     = 16;

    reg clk = 0;
    reg rstn = 0;
    reg start = 0;

    wire busy, done;
    wire [31:0] cycle_cnt;
    wire [19:0] bram_addr;
    wire bram_en, bram_we;
    wire [31:0] bram_wdata;
    reg  [31:0] bram_rdata;

    // 256KB 字存储（65536 x 32bit）
    reg [31:0] mem [0:65535];

    always #5 clk = ~clk;      // 100MHz

    // 同步读（1 拍延迟）；写同步
    always @(posedge clk) begin
        if (bram_en) bram_rdata <= mem[bram_addr[19:2]];
        if (bram_we) mem[bram_addr[19:2]] <= bram_wdata;
    end

    conv_engine #(
        .OC_PAR(16),
        .OW_CHUNK(32)
    ) dut (
        .clk(clk), .rstn(rstn),
        .start(start),
        .c_in(C_IN[15:0]), .c_out(C_OUT[15:0]),
        .h_in(H[15:0]), .w_in(W[15:0]),
        .wgt_base(24'h000000),
        .in_base (24'h010000),
        .out_base(24'h020000),
        .busy(busy), .done(done), .cycle_cnt(cycle_cnt),
        .bram_addr(bram_addr), .bram_en(bram_en),
        .bram_we(bram_we), .bram_wdata(bram_wdata), .bram_rdata(bram_rdata)
    );

    integer i;
    initial begin
        for (i = 0; i < 65536; i = i + 1) mem[i] = 32'h0;
        $readmemh("D:/fpga_plate_recognition/zynq_project/rtl/sim/weights.hex", mem, 0, 287);          // 1152B / 4
        $readmemh("D:/fpga_plate_recognition/zynq_project/rtl/sim/input.hex",   mem, 16384, 16511);    // 0x10000/4

        repeat (5) @(posedge clk);
        rstn <= 1;
        repeat (5) @(posedge clk);

        start <= 1;
        @(posedge clk);
        start <= 0;

        // 等 done
        wait (done === 1'b1);
        repeat (5) @(posedge clk);

        $display("conv done, cycles = %0d", cycle_cnt);
        $writememh("D:/fpga_plate_recognition/zynq_project/rtl/sim/out.hex", mem, 32768, 36863);       // 0x20000/4 起，4096 个字
        $display("output dumped");
        $finish;
    end

// 调试
    always @(posedge clk) begin
        if (dut.st == 4'd5 && dut.row == 3 && dut.ow == 0 && dut.ocb == 0)
            $display("MAC r3 ic=%0d kh=%0d kw=%0d in=%0d w0=%0d acc0=%0d", dut.ic, dut.kh, dut.kw, dut.in_word_byte, dut.wbuf[0], dut.acc[0]);
        if (dut.st == 4'd1)   // S_CLEAR
            $display("CLEAR row=%0d ocb=%0d", dut.row, dut.ocb);
    end

    // 超时保护
    initial begin
        #20_000_000;
        $display("TIMEOUT! cycles=%0d state=%0d", cycle_cnt, dut.st);
        $finish;
    end

endmodule
