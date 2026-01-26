# 本文件部分代码部分参考 https://github.com/CosmosShadow/gptpdf (MIT License)
# 并在此基础上做了改进

import os
import re
import base64
from typing import List, Tuple, Optional, Dict
import fitz
import shapely.geometry as sg
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity
import concurrent.futures
import logging
from openai import OpenAI
import pypandoc
from os import getenv
from dotenv import load_dotenv
import time
from shapely.ops import unary_union

# This Default Prompt Using Chinese and could be changed to other languages.

def _is_near(rect1, rect2, distance = 20):
    """
    检查两个矩形是否靠近，如果它们之间的距离小于目标距离。
    @param rect1: 矩形1
    @param rect2: 矩形2
    @param distance: 目标距离
    @return: 是否靠近
    """
    return rect1.buffer(0.1).distance(rect2.buffer(0.1)) < distance

def _union_rects(rect1, rect2):
    """
    合并两个矩形。
    @param rect1: 矩形1
    @param rect2: 矩形2
    @return: 合并后的矩形
    """
    return sg.box(*(rect1.union(rect2).bounds))

def detect_and_filter_isolated_lines(rect_list,
                                     thickness_thresh=1.5,
                                     aspect_ratio=8,
                                     neighbor_distance=10,
                                     neighbor_count_threshold=2):
    """
    输入:
      rect_list: list of shapely.geometry (sg.box 或其它 BaseGeometry)
    参数:
      thickness_thresh: 认定为线的最大短边阈值（PDF 单位）
      aspect_ratio: 长宽比阈值（如 8 表示长度至少为短边的 8 倍）
      neighbor_distance: 邻近搜索的扩展距离
      neighbor_count_threshold: 周围至少多少其它线才保留这条线（>=）
    返回:
      filtered_rects: list of shapely.geometry，剔除了判定为孤立分隔线的元素
    """
    # 规范化输入：只保留 shapely geometry
    geoms = [g for g in rect_list if isinstance(g, BaseGeometry)]
    if not geoms:
        return []

    candidate_idxs = []  # indices in geoms that are candidate thin lines
    other_idxs = []      # indices that are not thin lines

    # classify thin-line candidates
    for idx, g in enumerate(geoms):
        x0, y0, x1, y1 = g.bounds
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        min_dim = min(w, h)
        max_dim = max(w, h)

        is_thin = (min_dim <= thickness_thresh)
        is_aspect = (max_dim / max(min_dim, 1e-9) >= aspect_ratio)

        if is_thin and is_aspect:
            candidate_idxs.append(idx)
        else:
            other_idxs.append(idx)

    # 若没有候选，直接返回原列表
    if not candidate_idxs:
        return geoms

    # 预取 candidate bounds 做快速数值邻近检测
    cand_boxes = [geoms[i].bounds for i in candidate_idxs]
    n = len(cand_boxes)
    to_remove = set()  # indices in geoms to remove (isolated separators)

    for ci, bbox in enumerate(cand_boxes):
        i = candidate_idxs[ci]
        x0, y0, x1, y1 = bbox
        max_dim = max(abs(x1 - x0), abs(y1 - y0))
        margin = neighbor_distance + max_dim * 0.05
        sx0, sy0, sx1, sy1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin

        neighbor_count = 0
        for cj, obox in enumerate(cand_boxes):
            if ci == cj:
                continue
            ox0, oy0, ox1, oy1 = obox
            # 快速 bbox overlap / proximity 判定
            if not (ox1 < sx0 or ox0 > sx1 or oy1 < sy0 or oy0 > sy1):
                neighbor_count += 1
                if neighbor_count >= neighbor_count_threshold:
                    break

        # 若邻居数小于阈值，则判为孤立分隔线 -> 标记删除
        if neighbor_count < neighbor_count_threshold:
            to_remove.add(i)

    # 构建过滤后列表（去掉被标记的孤立线）
    filtered = [g for idx, g in enumerate(geoms) if idx not in to_remove]
    return filtered


def _fast_merge_rects(rect_list, distance = 20, horizontal_distance = None, buffer_resolution=8):
    """
    快速合并列表中的矩形 (rect_list: list of shapely geometries)
    使用 buffer(distance/2) + unary_union 的方式，返回合并后的 shapely.box 列表
    """
    if not rect_list:
        return []

    # 统一输入为 shapely geometries
    geoms = []
    for r in rect_list:
        if isinstance(r, BaseGeometry):
            geoms.append(r)
        elif isinstance(r, (tuple, list)) and len(r) == 4:
            geoms.append(sg.box(*r))
        else:
            # 跳过未知类型
            continue

    buffered = [g.buffer(distance/2.0, resolution=buffer_resolution) for g in geoms]
    merged = unary_union(buffered)

    # 方案：将并集按组件转为 axis-aligned boxes，然后对每个 box 做数值收缩（更可控）
    try_shrink = distance / 2.0 - 0.1  # 留点余量避免过度收缩
    merged_list = []
    if merged.is_empty:
        return []

    comps = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    for comp in comps:
        # 先修复可能的无效几何（保留原逻辑）
        if explain_validity(comp) != 'Valid Geometry':
            try:
                comp = comp.buffer(0)
            except Exception:
                continue
        x0, y0, x1, y1 = comp.bounds
        # 数值收缩：注意不要把 box 反转
        nx0, ny0, nx1, ny1 = x0 + try_shrink, y0 + try_shrink, x1 - try_shrink, y1 - try_shrink
        if nx1 <= nx0 or ny1 <= ny0:
            # 收缩后无效：回退到原 bounds（或跳过，根据需求选择）
            merged_list.append(sg.box(x0, y0, x1, y1))
        else:
            merged_list.append(sg.box(nx0, ny0, nx1, ny1))

    return merged_list

def _adsorb_rects_to_rects(source_rects, target_rects, distance=10):
    """
    当距离小于目标距离时，将一组矩形吸附到另一组矩形。
    @param source_rects: 源矩形列表
    @param target_rects: 目标矩形列表
    @param distance: 目标距离
    @return: 吸附后的源矩形列表和目标矩形列表
    """
    new_source_rects = []
    for text_area_rect in source_rects:
        adsorbed = False
        for index, rect in enumerate(target_rects):
            if _is_near(text_area_rect, rect, distance):
                rect = _union_rects(text_area_rect, rect)
                target_rects[index] = rect
                adsorbed = True
                break
        if not adsorbed:
            new_source_rects.append(text_area_rect)
    return new_source_rects, target_rects

def _parse_rects(page):
    """
    解析页面中的绘图，并合并相邻的矩形。
    @param page: 页面
    @return: 矩形列表
    """
    # time_start = time.time()
    # print(f"Parsing page {page.number}...")

    # 提取画的内容
    drawings = page.get_drawings()
    # 过滤短水平直线
    is_short_line = lambda x: abs(x['rect'][3] - x['rect'][1]) < 1 and abs(x['rect'][2] - x['rect'][0]) < 30
    drawings = [d for d in drawings if not is_short_line(d)]
    # 转为 shapely boxes
    drawing_boxes = [sg.box(*d['rect']) for d in drawings]

    # 提取图片区域
    images = page.get_image_info()
    image_rects = [sg.box(*img['bbox']) for img in images]

    # 把 drawing_boxes 和 image_rects 合并成候选 rect 列表，先检测并剔除孤立线
    initial_rects = drawing_boxes + image_rects
    # filtered_rects 为去掉“孤立分隔线”的结果（shapely geometry 列表）
    filtered_rects = detect_and_filter_isolated_lines(
        initial_rects,
        thickness_thresh=1.5,
        aspect_ratio=8,
        neighbor_distance=10,
        neighbor_count_threshold=2
    )
    rect_list = filtered_rects

    # 接着用 fast merge（buffer + unary_union）
    merged_rects = _fast_merge_rects(filtered_rects, distance=10, horizontal_distance=100)
    merged_rects = [rect for rect in merged_rects if explain_validity(rect) == 'Valid Geometry']

    # time_after_first_merge = time.time()
    # print(f"  first merge_rects time: {time_after_first_merge - time_after_images:.4f} seconds, merged rects num: {len(merged_rects)}.")

    # 将大文本区域和小文本区域分开处理: 大文本相小合并，小文本靠近合并
    is_large_content = lambda x: (len(x[4]) / max(1, len(x[4].split('\n')))) > 5
    small_text_area_rects = [sg.box(*x[:4]) for x in page.get_text('blocks') if not is_large_content(x)]
    large_text_area_rects = [sg.box(*x[:4]) for x in page.get_text('blocks') if is_large_content(x)]
    _, merged_rects = _adsorb_rects_to_rects(large_text_area_rects, merged_rects, distance=0.1) # 完全相交
    _, merged_rects = _adsorb_rects_to_rects(small_text_area_rects, merged_rects, distance=5) # 靠近

    # time_after_adsorb = time.time()
    # print(f"  adsorb_rects_to_rects time: {time_after_adsorb - time_after_first_merge:.4f} seconds, merged rects num: {len(merged_rects)}.")

    # 再次自身合并
    merged_rects = _fast_merge_rects(merged_rects, distance=10)

    # time_after_second_merge = time.time()
    # print(f"  second merge_rects time: {time_after_second_merge - time_after_adsorb:.4f} seconds, merged rects num: {len(merged_rects)}.")

    # 过滤比较小的矩形
    merged_rects = [rect for rect in merged_rects if rect.bounds[2] - rect.bounds[0] > 20 and rect.bounds[3] - rect.bounds[1] > 20]

    # time_end = time.time()
    # print(f"_parse_rects time: {time_end - time_start:.4f} seconds, rects num: {len(merged_rects)}. END successfully.")

    return [rect.bounds for rect in merged_rects]

def _parse_pdf_to_images(pdf_path, output_dir = './'):
    """
    解析PDF文件到图片，并保存到输出目录。
    @param pdf_path: PDF文件路径
    @param output_dir: 输出目录
    @return: 图片信息列表(图片路径, 矩形图片路径列表), 每页处理时间列表
    """
    pdf_document = fitz.open(pdf_path)
    image_infos = []
    page_times = []  # 新增：每页处理时间
    for page_index, page in enumerate(pdf_document):
        page_start = time.time()  # 记录每页开始时间
        rect_images = []
        rects = _parse_rects(page)
        for index, rect in enumerate(rects):
            fitz_rect = fitz.Rect(rect)
            fitz_rect = fitz_rect.intersect(page.rect)
            fitz_rect = fitz.Rect(round(fitz_rect.x0), round(fitz_rect.y0),
                                  round(fitz_rect.x1), round(fitz_rect.y1))
            if fitz_rect.x1 <= fitz_rect.x0 or fitz_rect.y1 <= fitz_rect.y0:
                print(f"  skip empty/invalid rect: {rect} -> intersected {fitz_rect}")
                continue
            pix = page.get_pixmap(clip=fitz_rect, matrix=fitz.Matrix(4, 4))
            name = f'{page_index}_{index}.png'
            pix.save(os.path.join(output_dir, name))
            rect_images.append(name)
            big_fitz_rect = fitz.Rect(fitz_rect.x0 - 1, fitz_rect.y0 - 1, fitz_rect.x1 + 1, fitz_rect.y1 + 1)
            page.draw_rect(big_fitz_rect, color=(1, 0, 0), width=1)
            text_x = fitz_rect.x0 + 2
            text_y = fitz_rect.y0 + 10
            text_rect = fitz.Rect(text_x, text_y - 9, text_x + 80, text_y + 2)
            page.draw_rect(text_rect, color=(1, 1, 1), fill=(1, 1, 1))
            page.insert_text((text_x, text_y), name, fontsize=10, color=(1, 0, 0))
        page_image_with_rects = page.get_pixmap(matrix=fitz.Matrix(3, 3))
        page_image = os.path.join(output_dir, f'{page_index}.png')
        page_image_with_rects.save(page_image)
        image_infos.append((page_image, rect_images))
        page_end = time.time()
        page_times.append(page_end - page_start)  # 新增：记录每页耗时
    pdf_document.close()
    return image_infos, page_times  # 返回每页耗时

def extract_pdf_images(pdf_path, output_dir='./'):
    """
    只提取PDF中的图片区域并保存到output_dir。
    返回所有保存的图片路径，以及每页处理时间。
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    image_infos, page_times = _parse_pdf_to_images(pdf_path, output_dir=output_dir)
    all_rect_images = []
    for page_image, rect_images in image_infos:
        all_rect_images.extend([os.path.join(output_dir, img) for img in rect_images])
    return all_rect_images, page_times  # 返回每页耗时

if __name__ == "__main__":
    pdf_path = r"pdfs\1904.00962.pdf"
    img_dir = r"putput"
    extract_pdf_images(pdf_path, output_dir=img_dir)


    # pdf_dir = r"test1"
    # pdf_paths = []
    # for root, _, files in os.walk(pdf_dir):
    #     for fn in files:
    #         if fn.lower().endswith(".pdf"):
    #             pdf_paths.append(os.path.join(root, fn))
    # time_list = []
    # page_time_list = []  # 新增：记录每页耗时

    # for pdf in pdf_paths:
    #     pdf_path = pdf
    #     img_dir = os.path.join('output_fast_merge', os.path.splitext(os.path.basename(pdf_path))[0])
    #     time1 = time.time()
    #     _, page_times = extract_pdf_images(pdf_path, output_dir=img_dir)
    #     time2 = time.time()

    #     print(f"finish processing PDF: {pdf_path}")
    #     print("fast_merge:", time2 - time1)
    #     time_list.append({
    #         "pdf": pdf_path,
    #         "time": time2 - time1
    #     })
    #     # 记录每页耗时
    #     for idx, t in enumerate(page_times):
    #         page_time_list.append({
    #             "pdf": pdf_path,
    #             "page": idx,
    #             "page_time": t
    #         })

    # # 分析总时间数据
    # max_time = max(item['time'] for item in time_list)
    # min_time = min(item['time'] for item in time_list)
    # avg_time = sum(item['time'] for item in time_list) / len(time_list)
    # middle_time = sorted(item['time'] for item in time_list)[len(time_list) // 2]
    # print(f"Max time: {max_time:.4f} seconds")
    # print(f"Min time: {min_time:.4f} seconds")
    # print(f"Avg time: {avg_time:.4f} seconds")
    # print(f"Middle time: {middle_time:.4f} seconds")

    # # 分析每页时间数据
    # if page_time_list:
    #     page_times_only = [item['page_time'] for item in page_time_list]
    #     max_page_time = max(page_times_only)
    #     min_page_time = min(page_times_only)
    #     avg_page_time = sum(page_times_only) / len(page_times_only)
    #     middle_page_time = sorted(page_times_only)[len(page_times_only) // 2]
    #     print(f"Per-page Max time: {max_page_time:.4f} seconds")
    #     print(f"Per-page Min time: {min_page_time:.4f} seconds")
    #     print(f"Per-page Avg time: {avg_page_time:.4f} seconds")
    #     print(f"Per-page Middle time: {middle_page_time:.4f} seconds")

    # import json
    # with open("fast_merge_times.json", "w", encoding="utf-8") as f:
    #     json.dump(time_list, f, ensure_ascii=False, indent=4)
    # with open("per_page_times.json", "w", encoding="utf-8") as f:
    #     json.dump(page_time_list, f, ensure_ascii=False, indent=4)