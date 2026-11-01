import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from tqdm import tqdm
import matplotlib.pyplot as plt

from dataset import PlateDataset
from model import LPRNet

# 字符集直接写在文件里，和 6_test.py 保持一致
CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣'
char2idx = {c: i for i, c in enumerate(CHARS)}
idx2char = {i: c for c, i in char2idx.items()}

def encode_label(label):
    return [char2idx[c] for c in label]

# 加载数据
train_dataset = PlateDataset('split/train', 'labels.txt')
val_dataset = PlateDataset('split/val', 'labels.txt')
train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

print(f'训练集: {len(train_dataset)} 张')
print(f'验证集: {len(val_dataset)} 张')

# 模型
model = LPRNet(num_classes=len(CHARS)).cuda()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=1e-3)

# 训练
best_acc = 0
train_losses = []
val_accs = []

for epoch in range(100):
    model.train()
    train_loss = 0
    for imgs, labels in tqdm(train_loader, desc=f'Epoch {epoch}'):
        imgs = imgs.cuda()
        targets = torch.tensor([encode_label(l) for l in labels]).cuda()
        preds = model(imgs)
        loss = criterion(preds.reshape(-1, len(CHARS)), targets.reshape(-1))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        train_loss += loss.item()
    
    train_loss /= len(train_loader)
    train_losses.append(train_loss)
    
    # 验证
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for imgs, labels in val_loader:
            imgs = imgs.cuda()
            preds = model(imgs)
            pred_strs = preds.argmax(dim=2)
            for pred, true in zip(pred_strs, labels):
                pred_label = ''.join([idx2char[i.item()] for i in pred])
                if pred_label == true:
                    correct += 1
                total += 1
    acc = correct / total * 100
    val_accs.append(acc)
    print(f'Epoch {epoch}: loss={train_loss:.4f}, val_acc={acc:.2f}%')
    
    if acc > best_acc:
        best_acc = acc
        torch.save(model.state_dict(), 'best_model.pth')
        print(f'  保存最佳模型: acc={acc:.2f}%')

# 画曲线
plt.figure(figsize=(12, 5))
plt.subplot(1, 2, 1)
plt.plot(train_losses)
plt.title('Train Loss')
plt.subplot(1, 2, 2)
plt.plot(val_accs)
plt.title('Val Accuracy')
plt.savefig('training_curve.png')
plt.show()