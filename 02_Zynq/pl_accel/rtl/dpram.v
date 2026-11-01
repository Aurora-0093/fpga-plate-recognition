// dpram.v —— 真双口 RAM（32bit x 131072 = 512KB）
//   整字写（任意字节使能触发整字写），BRAM 推断友好。
`default_nettype none

module dpram #(
    parameter ADDR_W = 17,
    parameter DATA_W = 32
)(
    input  wire             clka,
    input  wire             ena,
    input  wire [3:0]       wea,
    input  wire [ADDR_W-1:0] addra,
    input  wire [DATA_W-1:0] dina,
    output reg  [DATA_W-1:0] douta,

    input  wire             clkb,
    input  wire             enb,
    input  wire [3:0]       web,
    input  wire [ADDR_W-1:0] addrb,
    input  wire [DATA_W-1:0] dinb,
    output reg  [DATA_W-1:0] doutb
);

    reg [DATA_W-1:0] mem [0:(1 << ADDR_W) - 1];

    // Port A
    always @(posedge clka) begin
        if (ena) begin
            if (wea != 4'b0000)
                mem[addra] <= dina;
            douta <= mem[addra];
        end
    end

    // Port B
    always @(posedge clkb) begin
        if (enb) begin
            if (web != 4'b0000)
                mem[addrb] <= dinb;
            doutb <= mem[addrb];
        end
    end

endmodule
`default_nettype wire
