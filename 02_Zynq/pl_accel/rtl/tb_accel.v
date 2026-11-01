// tb_accel.v —— conv_accel 仿真台（含 BRAM 模型）
//   字节地址： 0x0000 控制区 | 0x1000 权重 | 0x10000 输入 | 0x20000 输出
`timescale 1ns/1ps

module tb_accel;
    localparam C_IN = 4, C_OUT = 32, H = 8, W = 16;

    reg clk = 0, rstn = 0;
    always #5 clk = ~clk;

    wire [19:0] bram_addr;
    wire        bram_en, bram_we;
    wire [31:0] bram_wdata;
    reg  [31:0] bram_rdata;

    reg [31:0] mem [0:131071];      // 512KB

    always @(posedge clk) begin
        if (bram_en) bram_rdata <= mem[bram_addr[16:0]];   // 现在是字地址
        if (bram_we) mem[bram_addr[16:0]] <= bram_wdata;
    end

    conv_accel #(.OC_PAR(16), .OW_CHUNK(8)) dut (
        .clk(clk), .rstn(rstn),
        .bram_addr(bram_addr), .bram_en(bram_en), .bram_we(bram_we),
        .bram_wdata(bram_wdata), .bram_rdata(bram_rdata)
    );

    integer i;
    initial begin
        for (i = 0; i < 131072; i = i + 1) mem[i] = 32'h0;

        // 权重 -> 字节 0x1000 (字 0x400)；输入 -> 字节 0x10000 (字 0x4000)
        $readmemh("D:/fpga_plate_recognition/zynq_project/rtl/sim/weights.hex", mem, 1024, 1311);
        $readmemh("D:/fpga_plate_recognition/zynq_project/rtl/sim/input.hex",   mem, 16384, 16511);

        repeat (5) @(posedge clk);
        rstn <= 1;
        repeat (5) @(posedge clk);

        // 写参数（ARM 角色）
        mem[1] = C_IN;  mem[2] = C_OUT; mem[3] = H; mem[4] = W;
        mem[5] = 24'h001000;   // 权重偏移
        mem[6] = 24'h010000;   // 输入偏移
        mem[7] = 24'h020000;   // 输出偏移
        mem[0] = 32'h1;        // start

        // 等 done
        wait (mem[0][2] === 1'b1);
        repeat (10) @(posedge clk);

        $display("accel done, cycles=%0d", mem[8]);
        $writememh("D:/fpga_plate_recognition/zynq_project/rtl/sim/out_accel.hex", mem, 32768, 36863);
        $display("dumped");
        $finish;
    end

    initial begin
        #50_000_000;
        $display("TIMEOUT state=%0d", dut.cst);
        $finish;
    end

    // 打印引擎实际收到的参数
    initial begin
        wait (dut.cst == 4'd6);      // C_GO
        $display("PARAMS c_in=%0d c_out=%0d h=%0d w=%0d wgt=%h in=%h out=%h",
                 dut.c_in_r, dut.c_out_r, dut.h_in_r, dut.w_in_r,
                 dut.wgt_r, dut.in_r, dut.out_r);
    end
endmodule
