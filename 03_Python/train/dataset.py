import os
import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

class PlateDataset(Dataset):
    def __init__(self, root_dir, labels_file, img_w=128, img_h=32):
        self.root_dir = root_dir
        self.img_w = img_w
        self.img_h = img_h
        self.samples = []
        
        with open(labels_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                filename, label = line.split()
                # 只保留属于当前 split 的图片
                if os.path.exists(os.path.join(root_dir, filename)):
                    self.samples.append((filename, label))
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        filename, label = self.samples[idx]
        img = cv2.imread(os.path.join(self.root_dir, filename), cv2.IMREAD_GRAYSCALE)
        img = cv2.resize(img, (self.img_w, self.img_h))
        img = img.astype(np.float32) / 255.0
        img = torch.from_numpy(img).unsqueeze(0)
        return img, label
