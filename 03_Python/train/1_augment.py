import os
import cv2
import albumentations as A

# 手动指定：文件名 → 车牌号
file_label_map = {
    # 沪B67890（8 张 + 新增 3 张 FPGA 采集）
    'hu_B67890_1.jpg': '沪B67890',
    'hu_B67890_2.jpg': '沪B67890',
    'hu_B67890_3.jpg': '沪B67890',
    'hu_B67890_4.jpg': '沪B67890',
    'hu_B67890_5.jpg': '沪B67890',
    'hu_B67890_6.jpg': '沪B67890',
    'hu_B67890_7.jpg': '沪B67890',
    'hu_B67890_8.jpg': '沪B67890',
    'hu_B67890_9.jpg': '沪B67890',
    'hu_B67890_10.jpg': '沪B67890',
    'hu_B67890_11.jpg': '沪B67890',
    'hu_B67890_12.jpg': '沪B67890',
    'hu_B67890_13.jpg': '沪B67890',
    'hu_B67890_14.jpg': '沪B67890',
    # 陕E86420（13 张 + 新增 3 张 FPGA 采集）
    'shan_E86420_1.jpg': '陕E86420',
    'shan_E86420_2.jpg': '陕E86420',
    'shan_E86420_3.jpg': '陕E86420',
    'shan_E86420_4.jpg': '陕E86420',
    'shan_E86420_5.jpg': '陕E86420',
    'shan_E86420_6.jpg': '陕E86420',
    'shan_E86420_7.jpg': '陕E86420',
    'shan_E86420_8.jpg': '陕E86420',
    'shan_E86420_9.jpg': '陕E86420',
    'shan_E86420_10.jpg': '陕E86420',
    'shan_E86420_11.jpg': '陕E86420',
    'shan_E86420_12.jpg': '陕E86420',
    'shan_E86420_13.jpg': '陕E86420',
    'shan_E86420_14.jpg': '陕E86420',
    'shan_E86420_15.jpg': '陕E86420',
    'shan_E86420_16.jpg': '陕E86420',
    'shan_E86420_17.jpg': '陕E86420',
    'shan_E86420_18.jpg': '陕E86420',
    'shan_E86420_19.jpg': '陕E86420',
    # 粤C54321（9 张 + 新增 3 张 FPGA 采集）
    'yue_C54321_1.jpg': '粤C54321',
    'yue_C54321_2.jpg': '粤C54321',
    'yue_C54321_3.jpg': '粤C54321',
    'yue_C54321_4.jpg': '粤C54321',
    'yue_C54321_5.jpg': '粤C54321',
    'yue_C54321_6.jpg': '粤C54321',
    'yue_C54321_7.jpg': '粤C54321',
    'yue_C54321_8.jpg': '粤C54321',
    'yue_C54321_9.jpg': '粤C54321',
    'yue_C54321_10.jpg': '粤C54321',
    'yue_C54321_11.jpg': '粤C54321',
    'yue_C54321_12.jpg': '粤C54321',
    'yue_C54321_13.jpg': '粤C54321',
    'yue_C54321_14.jpg': '粤C54321',
    'yue_C54321_15.jpg': '粤C54321',
    'hu_B67890_15.jpg': '沪B67890',
    'hu_B67890_16.jpg': '沪B67890',
    'hu_B67890_17.jpg': '沪B67890',
    'hu_B67890_18.jpg': '沪B67890',
    'hu_B67890_19.jpg': '沪B67890',
    'hu_B67890_20.jpg': '沪B67890',
    'hu_B67890_21.jpg': '沪B67890',
    'hu_B67890_22.jpg': '沪B67890',
    'yue_C54321_16.jpg': '粤C54321',
    'yue_C54321_17.jpg': '粤C54321',
    'yue_C54321_18.jpg': '粤C54321',
    'yue_C54321_19.jpg': '粤C54321',
    'yue_C54321_20.jpg': '粤C54321',
    'yue_C54321_21.jpg': '粤C54321',
    'yue_C54321_22.jpg': '粤C54321',
    'yue_C54321_23.jpg': '粤C54321',
    'yue_C54321_24.jpg': '粤C54321',
    'shan_E86420_20.jpg': '陕E86420',
    'shan_E86420_21.jpg': '陕E86420',
    'shan_E86420_22.jpg': '陕E86420',
    'shan_E86420_23.jpg': '陕E86420',
    'shan_E86420_24.jpg': '陕E86420',
    'shan_E86420_25.jpg': '陕E86420',
    'shan_E86420_26.jpg': '陕E86420',
    'shan_E86420_27.jpg': '陕E86420',
    'shan_E86420_28.jpg': '陕E86420',
    # 赣DF0002（6 张 FPGA 采集 + 新增 8 张串口采集）
    'gan_DF0002_1.jpg': '赣DF0002',
    'gan_DF0002_2.jpg': '赣DF0002',
    'gan_DF0002_3.jpg': '赣DF0002',
    'gan_DF0002_4.jpg': '赣DF0002',
    'gan_DF0002_5.jpg': '赣DF0002',
    'gan_DF0002_6.jpg': '赣DF0002',
    'gan_DF0002_7.jpg': '赣DF0002',
    'gan_DF0002_8.jpg': '赣DF0002',
    'gan_DF0002_9.jpg': '赣DF0002',
    'gan_DF0002_10.jpg': '赣DF0002',
    'gan_DF0002_11.jpg': '赣DF0002',
    'gan_DF0002_12.jpg': '赣DF0002',
    'gan_DF0002_13.jpg': '赣DF0002',
    'gan_DF0002_14.jpg': '赣DF0002',

    # 贵AF0236（7 张 FPGA 采集 + 新增 3 张串口采集）
    'gui_AF0236_1.jpg': '贵AF0236',
    'gui_AF0236_2.jpg': '贵AF0236',
    'gui_AF0236_3.jpg': '贵AF0236',
    'gui_AF0236_4.jpg': '贵AF0236',
    'gui_AF0236_5.jpg': '贵AF0236',
    'gui_AF0236_6.jpg': '贵AF0236',
    'gui_AF0236_7.jpg': '贵AF0236',
    'gui_AF0236_8.jpg': '贵AF0236',
    'gui_AF0236_9.jpg': '贵AF0236',
    'gui_AF0236_10.jpg': '贵AF0236',
    # 沪B67890（新增 2 张串口采集）
    'hu_B67890_23.jpg': '沪B67890',
    'hu_B67890_24.jpg': '沪B67890',
}

transform = A.Compose([
    A.RandomBrightnessContrast(p=0.8),
    A.Rotate(limit=5, p=0.5),
    A.RandomScale(scale_limit=0.1, p=0.5),
    A.GaussNoise(p=0.5),
    A.GaussianBlur(blur_limit=3, p=0.3),
    A.Resize(32, 128),
])

raw_dir = 'raw'
aug_dir = 'augmented'
os.makedirs(aug_dir, exist_ok=True)

labels = []

for filename in os.listdir(raw_dir):
    if not filename.lower().endswith(('.jpg', '.png', '.jpeg')):
        continue
    if filename not in file_label_map:
        print(f"跳过未定义文件: {filename}")
        continue
    
    filepath = os.path.join(raw_dir, filename)
    img = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"读取失败: {filename}")
        continue
    img = cv2.resize(img, (128, 32))
    
    plate = file_label_map[filename]
    
    for i in range(300):
        aug = transform(image=img)['image']
        save_name = f"{os.path.splitext(filename)[0]}_{i:04d}.jpg"
        cv2.imwrite(os.path.join(aug_dir, save_name), aug)
        labels.append(f"{save_name} {plate}")

with open('labels.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(labels))

print(f"增强完成，共生成 {len(labels)} 张图片")