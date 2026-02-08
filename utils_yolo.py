import os
import shutil
import cv2
import numpy as np
from pdf2image import convert_from_path
from ultralytics import YOLO
from PIL import Image

def extract_pdf_images(pdf_path: str, base_output_dir: str):

    img_dir_infer = os.path.join(base_output_dir, 'images_inference') # 用于YOLO推理的低分图
    img_dir_highres = os.path.join(base_output_dir, 'images_highres') # 用于最终裁剪的高清图
    crop_dir = base_output_dir
    annotated_dir = base_output_dir
    model_path = 'best.pt'

    # 推理尺寸
    INFER_SIZE = (640, 640)

    # 创建文件夹
    for d in [img_dir_infer, img_dir_highres]:
        os.makedirs(d, exist_ok=True)

    # 清空旧数据
    for d in [img_dir_infer, img_dir_highres]:
        for f in os.listdir(d):
            try:
                os.remove(os.path.join(d, f))
            except Exception as e:
                print(f"删除失败 {f}: {e}")

    print("正在处理PDF...")
    pdf_page_map = {}

    pages = convert_from_path(pdf_path, dpi=300)
    for i, page in enumerate(pages):
        page_num = i + 1
        filename = f"{page_num}.png"  # 统一为png
        
        # --- 1. 保存用于最后裁剪/标注的高清原图 ---
        highres_path = os.path.join(img_dir_highres, filename)
        page.save(highres_path, 'PNG')  # 保存为PNG
        
        # --- 2. 保存用于YOLO推理的缩放图 ---
        infer_path = os.path.join(img_dir_infer, filename)
        page_rgb = page.convert('RGB')
        page_resized = page_rgb.resize(INFER_SIZE, Image.LANCZOS)
        page_resized.save(infer_path, 'PNG')  # 保存为PNG
        
        pdf_page_map[filename] = page_num

    print("图片预处理完成。")

    # --- YOLO推理 ---
    print("正在进行YOLO推理、高清映射与标注...")
    model = YOLO(model_path)

    # 推理使用的是 Resize 后的图片文件夹
    results = model.predict(
        source=img_dir_infer,
        save=False, # 我们自己处理保存
        save_txt=False,
        conf=0.3,
        imgsz=640
    )

    for result in results:
        path = result.path
        filename = os.path.basename(path)
        page_num_x = pdf_page_map.get(filename, 0)
        
        # 读取高清原图用于裁剪和标注
        highres_path = os.path.join(img_dir_highres, filename)
        if not os.path.exists(highres_path):
            print(f"警告：找不到高清原图 {highres_path}")
            continue
            
        # cv2读取图片 (BGR格式)
        highres_img = cv2.imread(highres_path)
        if highres_img is None:
            continue
            
        h_high, w_high, _ = highres_img.shape
        
        # 计算缩放比例 (高清尺寸 / 推理尺寸)
        # 注意：YOLO推理时如果图片非正方形，可能会由padding。
        # 但这里我们在预处理时强制resize成了(640,640)，所以是直接拉伸映射。
        scale_x = w_high / INFER_SIZE[0]
        scale_y = h_high / INFER_SIZE[1]
        
        annotated_img = highres_img.copy()
        img_idx_y = 0
        names = result.names
        boxes = result.boxes
        
        if len(boxes) > 0:
            # 按y坐标排序
            box_list = sorted(boxes, key=lambda x: x.xyxy[0][1])
            
            for box in box_list:
                # 获取 640x640 尺度下的坐标
                x1_inf, y1_inf, x2_inf, y2_inf = box.xyxy[0].cpu().numpy()
                
                # --- 坐标映射回原图 ---
                x1 = int(x1_inf * scale_x)
                y1 = int(y1_inf * scale_y)
                x2 = int(x2_inf * scale_x)
                y2 = int(y2_inf * scale_y)
                
                # 边界保护
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w_high, x2), min(h_high, y2)
                
                cls_id = int(box.cls[0])
                
                # 方案：根据类别ID判断
                if cls_id == 0: 
                    prefix = "Table" 
                elif cls_id == 1:
                    prefix = "Fig"   
                else:
                    prefix = "Unknown"
                
                label_name = f"{prefix}_{page_num_x}_{img_idx_y}"
                full_file_name = f"{label_name}.png"
                
                # --- 1. 高清裁剪保存 ---
                crop_img = highres_img[y1:y2, x1:x2]
                if crop_img.size > 0:
                    cv2.imwrite(os.path.join(crop_dir, full_file_name), crop_img)
                
                # --- 2. 高清原图标注 ---
                box_thickness = 4 
                font_scale = 1.6   
                text_thickness = 3 
                
                # 画框
                cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (0, 0, 255), box_thickness)
                
                # 文本背景和文字
                (text_w, text_h), baseline = cv2.getTextSize(full_file_name, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness)
                
                # 确保标签不画出界
                text_y_pos = y1 - 10 if y1 - 10 > text_h else y1 + text_h + 10
                
                cv2.rectangle(annotated_img, (x1, text_y_pos - text_h - 5), (x1 + text_w, text_y_pos + 5), (0, 0, 255), -1)
                cv2.putText(annotated_img, full_file_name, (x1, text_y_pos), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), text_thickness)
                
                img_idx_y += 1
                
        save_annotated_path = os.path.join(annotated_dir, f"{page_num_x}.png")  # 统一为png
        cv2.imwrite(save_annotated_path, annotated_img)

    # 删除推理用的缩放图和高清图
    shutil.rmtree(img_dir_infer)
    shutil.rmtree(img_dir_highres)


if __name__ == "__main__":
    pdf_path = r"D:\pdf_dataset\pdf_files\test.pdf"  # 替换为你的PDF路径
    output_dir = "test_images"   # 替换为你想要的输出目录
    extract_pdf_images(pdf_path, output_dir)