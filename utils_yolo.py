import os
import shutil
import cv2
import numpy as np
from pdf2image import convert_from_path
from doclayout_yolo import YOLOv10
from PIL import Image

def get_box_iou_x(box1, box2):
    """计算水平方向的交并比/最小宽度比，用于检查对齐情况。"""
    x1_min, _, x1_max, _ = box1
    x2_min, _, x2_max, _ = box2
    
    inter_min = max(x1_min, x2_min)
    inter_max = min(x1_max, x2_max)
    
    if inter_max <= inter_min:
        return 0.0
    
    intersection = inter_max - inter_min
    min_width = min((x1_max - x1_min), (x2_max - x2_min))
    
    return intersection / min_width if min_width > 0 else 0

def is_main_body(cls_name):
    """检查类别是否为主体（表格网格或图片本身）。"""
    name_lower = cls_name.lower()
    # 只要不是 caption(标题) footnote(脚注) note(批注)，都视为主体
    if 'caption' in name_lower or 'footnote' in name_lower or 'note' in name_lower:
        return False
    return True

def merge_boxes(predictions, class_names, img_h, img_w):
    """
    合并相邻的 Table/Caption/Footnote 和 Figure/Caption。.
    predictions: list of [x1, y1, x2, y2, conf, cls_id]
    """
    
    merge_groups = {
        'table': ['table', 'table_caption', 'table_footnote'],
        'figure': ['figure', 'picture', 'figure_caption', 'image', 'figure_footnote']
    }
    
    # 预计算类别信息
    cls_id_to_group = {} 
    cls_id_is_body = {}
    
    for cls_id, cls_name in class_names.items():
        name_lower = cls_name.lower()
        cls_id_is_body[cls_id] = is_main_body(cls_name)
        for group_name, keywords in merge_groups.items():
            if any(k in name_lower for k in keywords):
                cls_id_to_group[cls_id] = group_name
                break
    
    # 按Y坐标排序
    predictions.sort(key=lambda x: x[1])
    
    merged_predictions = []
    used_indices = set()
    
    v_thresh = img_h * 0.03 # 3% 高度阈值
    
    n = len(predictions)
    for i in range(n):
        if i in used_indices:
            continue
            
        current_box = predictions[i]
        x1, y1, x2, y2, conf, cls_id = current_box
        
        # 如果不可合并，优化宽度并跳过（这里暂时不做宽度强制拉伸，保持原样加入）
        if cls_id not in cls_id_to_group:
            merged_predictions.append(current_box)
            continue
            
        current_group = cls_id_to_group[cls_id]
        
        # 初始化合并状态
        m_x1, m_y1, m_x2, m_y2 = x1, y1, x2, y2
        m_confs = [conf]
        
        cluster_has_body = cls_id_is_body[cls_id]
        cluster_has_caption = 'caption' in class_names[int(cls_id)].lower()
        
        has_merged_in_pass = True
        while has_merged_in_pass:
            has_merged_in_pass = False
            # 内层循环查找后续可合并的框
            # 注意：这里的逻辑简化了递归合并，只做单次向下扫描。严格来说应该重新检查，但在排序列表上通常有效。
            for j in range(i + 1, n):
                if j in used_indices:
                    continue
                
                next_box = predictions[j]
                nx1, ny1, nx2, ny2, nconf, ncls_id = next_box
                next_name = class_names[int(ncls_id)].lower()
                
                # 1. 必须属于同一组
                if ncls_id not in cls_id_to_group or cls_id_to_group[ncls_id] != current_group:
                    continue
                
                # 2. 避免合并两个主体（例如两个独立的表格）
                next_is_body = cls_id_is_body[ncls_id]
                if cluster_has_body and next_is_body:
                    continue
                
                # 3. CAPTION 互斥逻辑
                next_is_caption = 'caption' in next_name
                if cluster_has_caption and next_is_caption:
                    if (ny1 - m_y2) > 5: # 距离稍远则认为是不同表格的标题
                        continue

                # 4. CAPTION-FOOTNOTE 顺序逻辑 (Table通常Caption在上方)
                if current_group == 'table' and cluster_has_body and next_is_caption:
                     continue

                # 5. 垂直距离检测
                dist = max(0, ny1 - m_y2)
                if dist > v_thresh:
                    continue
                
                # 6. 水平重叠检测 (放宽到 0.5)
                x_overlap = get_box_iou_x((m_x1, m_y1, m_x2, m_y2), (nx1, ny1, nx2, ny2))
                if x_overlap > 0.5:
                    # 合并
                    m_x1 = min(m_x1, nx1)
                    m_y1 = min(m_y1, ny1)
                    m_x2 = max(m_x2, nx2)
                    m_y2 = max(m_y2, ny2)
                    m_confs.append(nconf)
                    used_indices.add(j)
                    has_merged_in_pass = True # 标记发生了合并，可能延伸了边界，理论上可以触达更远的元素
                    
                    if next_is_body: cluster_has_body = True
                    if next_is_caption: cluster_has_caption = True
        
        new_conf = sum(m_confs) / len(m_confs)
        
        # 确定最终标签
        final_cls_id = cls_id
        
        # --- 全宽启发式规则 (可选，视需要开启) ---
        # box_width = m_x2 - m_x1
        # if box_width > (img_w * 0.70) and ('figure' in current_group or 'table' in current_group):
        #      m_x1 = max(0, img_w * 0.05)
        #      m_x2 = min(img_w, img_w * 0.95)

        merged_predictions.append([m_x1, m_y1, m_x2, m_y2, new_conf, final_cls_id])
        
    return merged_predictions

def extract_pdf_images(pdf_path: str, base_output_dir: str):
    """
    Integrates doclayout_yolo prediction and heuristic merging.
    Saves cropped images (Table_x_y.png, Fig_x_y.png) and annotated pages (1.png, 2.png) to base_output_dir.
    """
    # 使用相对路径，确保线上环境能正确找到模型文件
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(current_dir, "doclayout.pt")
    
    # Clean output dir
    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)
        
    img_dir_highres = os.path.join(base_output_dir, 'images_highres_temp') 
    os.makedirs(img_dir_highres, exist_ok=True)

    INFER_SIZE = 1024
    
    print(">>> Loading DocLayout-YOLO model...")
    device = 'cuda' if cv2.cuda.getCudaEnabledDeviceCount() > 0 else 'cpu'
    try:
        model = YOLOv10(model_path)
    except Exception as e:
        print(f"Error loading model: {e}")
        # 抛出异常，阻止程序继续静默运行，让 Streamlit 界面显示具体错误
        raise RuntimeError(f"YOLO模型加载失败，请检查模型文件是否存在于 {model_path}。详细错误: {e}")

    print(">>> Converting PDF to images...")
    pdf_page_map = {}
    
    # 1. Convert PDF to High-Res Images
    try:
        pages = convert_from_path(pdf_path, dpi=300)
    except Exception as e:
        print(f"PDF conversion failed: {e}")
        return

    for i, page in enumerate(pages):
        page_num = i + 1
        filename = f"{page_num}.png"
        highres_path = os.path.join(img_dir_highres, filename)
        page.save(highres_path, 'PNG')
        pdf_page_map[filename] = page_num

    print(">>> Enhancing recognition & merging...")

    highres_files = [os.path.join(img_dir_highres, f) for f in os.listdir(img_dir_highres) if f.endswith('.png')]
    # Sort files naturally
    highres_files.sort(key=lambda x: int(os.path.basename(x).split('.')[0]))

    for highres_path in highres_files:
        filename = os.path.basename(highres_path)
        page_num_x = pdf_page_map.get(filename, 0)
        
        # Inference
        try:
            results = model.predict(
                highres_path,
                imgsz=INFER_SIZE,
                conf=0.2,
                device=device,
                verbose=False
            )
        except Exception as e:
            print(f"Prediction failed for {filename}: {e}")
            continue
            
        result = results[0]
        orig_img = result.orig_img
        img_h, img_w = orig_img.shape[:2]
        
        names = result.names
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        cls_ids = result.boxes.cls.cpu().numpy()
        
        raw_preds = []
        for box, conf, cls_id in zip(boxes, confs, cls_ids):
            raw_preds.append([*box, conf, cls_id])
            
        merged_preds = merge_boxes(raw_preds, names, img_h, img_w)
        merged_preds.sort(key=lambda x: x[1])

        annotated_img = orig_img.copy()
        img_idx_y = 0
        
        has_annotations = False

        for mp in merged_preds:
            x1, y1, x2, y2, conf, cls_id = mp
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img_w, x2), min(img_h, y2)
            
            class_name = names[int(cls_id)].lower()
            
            prefix = "Unknown"
            if 'table' in class_name:
                prefix = "Table"
            elif 'figure' in class_name or 'picture' in class_name or 'image' in class_name:
                prefix = "Fig"
            
            # --- 关键修改：只保留Table和Fig，过滤所有Unknown和其他 ---
            if prefix == "Unknown":
                continue # 彻底跳过，不画框，不保存

            # 如果代码走到这里，说明是我们需要保留的 Table 或 Figure
            has_annotations = True 

            label_name = f"{prefix}_{page_num_x}_{img_idx_y}"
            full_file_name = f"{label_name}.png"
            
            # 1. 保存裁剪图
            crop_img = orig_img[y1:y2, x1:x2]
            if crop_img.size > 0:
                cv2.imwrite(os.path.join(base_output_dir, full_file_name), crop_img)
            
            # 2. 仅在全页图上标记Table和Figure
            color = (0, 0, 255) if prefix == "Table" else (255, 0, 0) # Table红，Figure蓝
            cv2.rectangle(annotated_img, (x1, y1), (x2, y2), color, 4)
            # Draw label background
            (text_w, text_h), _ = cv2.getTextSize(label_name, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
            # 确保文字背景不画出界
            text_bg_y1 = max(0, y1 - text_h - 10)
            cv2.rectangle(annotated_img, (x1, text_bg_y1), (x1 + text_w, y1), color, -1)
            
            text_y = max(text_h + 5, y1 - 5)
            cv2.putText(annotated_img, label_name, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            
            img_idx_y += 1
            
        # 3. 保存全页带有标注（仅含Table/Fig）的图片
        save_annotated_path = os.path.join(base_output_dir, f"{page_num_x}.png")
        cv2.imwrite(save_annotated_path, annotated_img)

    # Cleanup
    shutil.rmtree(img_dir_highres, ignore_errors=True)
    print(">>> Processing complete.")

if __name__ == "__main__":
    # 测试代码
    pdf_path = r"D:\test\visual-pdf-summary\test.pdf" 
    output_dir = r"D:\test\visual-pdf-summary\output_test"
    extract_pdf_images(pdf_path, output_dir)