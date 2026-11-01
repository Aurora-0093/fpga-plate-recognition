import torch
import cv2
import matplotlib.pyplot as plt
from torch.utils.data import DataLoader
from dataset import PlateDataset
from model import LPRNet

plt.rcParams['font.sans-serif'] = ['SimHei']  # 用黑体
plt.rcParams['axes.unicode_minus'] = False    # 负号正常显示

# 字符集直接写在文件里，不 import 外部文件
CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣'
idx2char = {i: c for i, c in enumerate(CHARS)}

model = LPRNet(num_classes=len(CHARS)).cuda()
model.load_state_dict(torch.load('best_model.pth'))
print('字符集长度:', len(CHARS))
print('模型输出维度:', model.fc.out_features)
print('idx2char 的键:', sorted(idx2char.keys()))
model.eval()

test_dataset = PlateDataset('split/test', 'labels.txt')
test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

correct = 0
total = 0
with torch.no_grad():
    for imgs, labels in test_loader:
        imgs = imgs.cuda()
        preds = model(imgs)
        pred_strs = preds.argmax(dim=2)
        for pred, true in zip(pred_strs, labels):
# 详细调试信息
            print('--- 单张调试 ---')
            print('pred 的形状:', pred.shape)
            print('pred 的类型:', type(pred))
            print('pred 的原始值:', pred)
            pred_np = pred.cpu().numpy().flatten()
            print('pred_np 的形状:', pred_np.shape)
            print('pred_np 的类型:', type(pred_np))
            print('pred_np 里的元素类型:', type(pred_np[0]))
            print('pred_np 里的值:', pred_np)
            
            pred_label = ''.join([idx2char[int(i)] for i in pred_np])
            if pred_label == true:
                correct += 1
            total += 1

print(f'测试集准确率: {correct / total * 100:.2f}%')

# 可视化前 5 张
model.eval()
plt.figure(figsize=(15, 5))
with torch.no_grad():
    for i in range(5):
        img, label = test_dataset[i]
        pred = model(img.unsqueeze(0).cuda())
        pred_np = pred.argmax(dim=2).cpu().numpy().flatten()
        pred_label = ''.join([idx2char[int(j)] for j in pred_np])
        plt.subplot(1, 5, i+1)
        plt.imshow(img.squeeze().cpu().numpy(), cmap='gray')
        plt.title(f'预测: {pred_label}\n真实: {label}')
        plt.axis('off')
plt.savefig('test_result.png')
plt.show()
