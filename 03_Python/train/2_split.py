"""按“原图”分组切分数据集（避免同一张原图的增强副本同时出现在 train/val/test）。

augmented 文件名规则：<原图名>_<4位序号>.jpg（如 hu_B67890_15_0042.jpg）
→ 同一原图的所有增强图归为一组，整组只进 train、val、test 其中之一；
并按车牌（文件名前缀 hu_B67890 / shan_E86420 / yue_C54321）分层，保证三块车牌分布均衡。

用法（在 plate_project 目录下）：
    python 2_split.py
"""

import os
import random
import re
import shutil

random.seed(42)

AUG_DIR = "augmented"
SPLIT_DIR = "split"
TRAIN_RATIO = 0.70
VAL_RATIO = 0.85          # 累计比例：train 70%，val 15%，test 15%


def source_group(filename: str) -> str:
    """去掉增强序号，得到原图分组名：hu_B67890_15_0042.jpg → hu_B67890_15"""
    stem = os.path.splitext(filename)[0]
    return re.sub(r"_\d{4}$", "", stem)


def plate_of(group: str) -> str:
    """hu_B67890_15 → hu_B67890"""
    return re.sub(r"_\d+$", "", group)


def main() -> None:
    groups = {}
    for f in os.listdir(AUG_DIR):
        if not f.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        groups.setdefault(source_group(f), []).append(f)

    plates = {}
    for g in groups:
        plates.setdefault(plate_of(g), []).append(g)

    train_groups, val_groups, test_groups = [], [], []
    for plate in sorted(plates):
        keys = sorted(plates[plate])
        random.shuffle(keys)
        n = len(keys)
        train_groups += keys[: int(n * TRAIN_RATIO)]
        val_groups += keys[int(n * TRAIN_RATIO): int(n * VAL_RATIO)]
        test_groups += keys[int(n * VAL_RATIO):]
        print(f"{plate}: 原图 {n} 组 -> train {len(keys[:int(n*TRAIN_RATIO)])} / "
              f"val {len(keys[int(n*TRAIN_RATIO):int(n*VAL_RATIO)])} / "
              f"test {len(keys[int(n*VAL_RATIO):])}")

    # 清空旧切分，保证可重复执行
    for name in ("train", "val", "test"):
        d = os.path.join(SPLIT_DIR, name)
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

    for name, grp in (("train", train_groups), ("val", val_groups), ("test", test_groups)):
        count = 0
        for g in grp:
            for f in groups[g]:
                shutil.copy(os.path.join(AUG_DIR, f), os.path.join(SPLIT_DIR, name, f))
                count += 1
        print(f"{name}: {len(grp)} 组原图 / {count} 张增强图")

    total = sum(len(groups[g]) for g in train_groups + val_groups + test_groups)
    print(f"合计: {len(groups)} 组原图 / {total} 张增强图（分组切分，组内不跨集）")


if __name__ == "__main__":
    main()
