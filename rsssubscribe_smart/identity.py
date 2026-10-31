import re
from typing import List

def _has_cjk(text: str) -> bool:
    return bool(re.search(r'[\u3400-\u9fff]', text or ''))

def identity_title_candidates(title: str, description: str = '') -> List[str]:
    title = str(title or '').strip(); description = str(description or '').strip()
    candidates = [title]
    for value in re.findall(r'[\[【]([^\]】]+)[\]】]', title):
        value = re.sub(r'\s+', ' ', value).strip()
        if _has_cjk(value): candidates.append(value)
    for pattern in (r'(?:片名|标题|名称|中文名)\s*[:：]\s*([^|\n;,；，]+)', r'^\s*([^|\n]+?)\s*[|｜]\s*(?:类型|类别|年份|Year)\s*[:：]'):
        for value in re.findall(pattern, description, flags=re.IGNORECASE):
            value = re.sub(r'\s+', ' ', value).strip(' []【】')
            if _has_cjk(value): candidates.append(value)
    first = re.split(r'[|｜\n]', description, maxsplit=1)[0].strip(' []【】')
    if _has_cjk(first) and 1 < len(first) <= 80 and not re.search(r'(简介|剧情|类型|大小|标签)\s*[:：]', first): candidates.append(first)
    result=[]
    for value in candidates:
        value=re.sub(r'\s+', ' ', value).strip()
        if value and value not in result: result.append(value)
    return result
