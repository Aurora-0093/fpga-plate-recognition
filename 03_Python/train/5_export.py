import torch
from model import LPRNet

CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣'

model = LPRNet(num_classes=len(CHARS)).cuda()
model.load_state_dict(torch.load('best_model.pth'))
model.eval()

dummy_input = torch.randn(1, 1, 32, 128).cuda()
torch.onnx.export(
    model, dummy_input, 'lprnet.onnx',
    input_names=['input'], output_names=['output'],
    opset_version=11
)
print('ONNX 模型已导出: lprnet.onnx')