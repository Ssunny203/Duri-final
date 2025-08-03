"""
학생 친화적 응답 포매터 - 모듈화 버전 v4
paper_type, c_img_url, dictionary image_url 지원
"""

import os
import json
import random
import urllib.parse
import requests
import sys
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
from contextlib import contextmanager

# 기존 search_system_v4 import
from search_system_v4 import FlexibleSearchSystem

# 환경 변수 로드
load_dotenv()

# ==================== 출력 제어 유틸리티 ====================
class SilentMode:
    """표준 출력을 임시로 비활성화"""
    def __init__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        
    def __enter__(self):
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


@contextmanager
def suppress_output():
    """출력을 억제하는 컨텍스트 매니저"""
    with SilentMode():
        yield


# ==================== 설정 관리 ====================
def get_default_config() -> Dict[str, Any]:
    """기본 설정 반환"""
    return {
        "greeting": "안녕! 나는 사회 공부를 도와주는 AI 친구야! 🌟",
        "main_concept": {
            "max_chars": 150
        },
        "images": {
            "max_count": 1
        },
        "related_links": {
            "max_count": 1
        },
        "problems": {
            "max_count": 2,
            "show_button": True
        }
    }


# ==================== 검색 모듈 ====================
class SearchModule:
    """검색 기능 캡슐화"""
    
    def __init__(self):
        with suppress_output():
            self.searcher = FlexibleSearchSystem()
    
    def search(self, query: str) -> Dict[str, Any]:
        """검색 실행 - 모든 출력 억제"""
        # 검색 시스템의 모든 출력을 억제
        with suppress_output():
            search_results = self.searcher.search_and_answer(query)
        
        return search_results


# ==================== 컨텐츠 추출 함수들 ====================
def extract_concept_ids(search_results: Dict[str, Any]) -> List[int]:
    """검색 결과에서 concept_id 추출"""
    concept_ids = set()
    
    for result in search_results.get('results', []):
        metadata = result.get('metadata', {})
        concept_id = metadata.get('concept_id')
        if concept_id:
            concept_ids.add(int(concept_id))
    
    concept_ids_list = list(concept_ids)
    return concept_ids_list


def extract_search_context(search_results: Dict[str, Any]) -> Dict[str, Any]:
    """검색 결과에서 컨텍스트 정보 추출"""
    context = {
        'dictionary_words': [],
        'has_faq_result': False,
        'primary_namespace': None
    }
    
    # 첫 번째 결과의 네임스페이스가 주요 네임스페이스
    if search_results.get('results'):
        context['primary_namespace'] = search_results['results'][0].get('namespace')
    
    for result in search_results.get('results', []):
        namespace = result.get('namespace')
        
        if namespace == 'dictionary':
            metadata = result.get('metadata', {})
            word = metadata.get('word')
            if word:
                context['dictionary_words'].append(word)
        
        elif namespace == 'faq':
            context['has_faq_result'] = True
    
    return context


def extract_main_concept(search_results: Dict[str, Any], max_chars: int = 150) -> Dict[str, Any]:
    """메인 컨셉 추출 및 축약"""
    main_concept = {
        "title": search_results['query'],
        "explanation": "",
        "source": "ai_generated",
        "user_query": search_results['query']
    }
    
    full_answer = search_results.get('answer', '')
    
    if not full_answer:
        return {
            "title": "검색 결과 없음",
            "explanation": "해당 내용을 찾을 수 없습니다.",
            "source": "none",
            "user_query": search_results['query']
        }
    
    # 답변 축약
    main_concept["explanation"] = shorten_text(full_answer, max_chars)
    
    # 신뢰도 정보 추가
    confidence = search_results.get('confidence', 'unknown')
    if confidence in ['low', 'very_low']:
        main_concept["explanation"] += " (참고용 정보)"
    
    return main_concept


def shorten_text(text: str, max_chars: int) -> str:
    """텍스트를 지정된 길이로 축약"""
    if len(text) <= max_chars:
        return text
    
    sentences = text.split('.')
    shortened = ""
    
    for sentence in sentences:
        if len(shortened + sentence) < max_chars:
            shortened += sentence + "."
        else:
            break
    
    if not shortened:
        shortened = text[:max_chars] + "..."
    
    return shortened.strip()


# ==================== 외부 API 함수들 ====================
def extract_core_keyword(query: str, concept_ids: List[int], supabase_client: Client) -> str:
    """질문에서 핵심 키워드 추출"""
    # concept_name 우선 사용
    if concept_ids:
        try:
            response = supabase_client.table('concept2').select("concept_name").eq('concept_id', concept_ids[0]).execute()
            if response.data:
                concept_name = response.data[0].get('concept_name', '')
                if concept_name:
                    return concept_name
        except Exception as e:
            pass
    
    # 우선순위 단어 체크
    priority_words = ['고조선', '단군왕검', '8조법', '청동기', '철기', '백제', '고구려', '신라', 
                     '조선', '고려', '삼국시대', '통일신라', '발해', '가야', '근초고왕']
    
    for word in priority_words:
        if word in query:
            return word
    
    # 조사 제거하고 키워드 추출
    words = query.split()
    particles = ['은', '는', '이', '가', '을', '를', '에', '에서', '으로', '와', '과', '의', '로', '이란', '란']
    keywords = []
    
    for word in words:
        cleaned_word = word
        for particle in particles:
            if word.endswith(particle) and len(word) > len(particle):
                cleaned_word = word[:-len(particle)]
                break
        
        if len(cleaned_word) >= 2 and not any(cleaned_word.endswith(end) for end in ['하다', '되다', '했어', '됐어', '해줘']):
            keywords.append(cleaned_word)
    
    if keywords:
        core_keyword = max(keywords, key=len)
        return core_keyword
    
    return query


def call_naver_api(query: str, client_id: str, client_secret: str) -> List[Dict]:
    """네이버 백과사전 API 호출"""
    url = "https://openapi.naver.com/v1/search/encyc.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    params = {
        "query": query,
        "display": 5,
        "sort": "sim"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get('items', [])
    except requests.exceptions.RequestException as e:
        return []


def get_related_links(query: str, concept_ids: List[int], supabase_client: Client, 
                     naver_client_id: str, naver_client_secret: str, max_count: int = 1) -> List[Dict]:
    """관련 링크 조회"""
    links = []
    
    if not naver_client_id or not naver_client_secret:
        # 기본 검색 링크 제공
        query_encoded = urllib.parse.quote(query)
        links.append({
            "title": f"네이버 지식백과에서 '{query}' 검색하기",
            "url": f"https://terms.naver.com/search.naver?query={query_encoded}",
            "description": "네이버 지식백과에서 더 많은 정보를 찾아보세요.",
            "source": "naver_search"
        })
        return links
    
    # 핵심 키워드 추출 및 API 호출
    core_keyword = extract_core_keyword(query, concept_ids, supabase_client)
    
    try:
        encyc_results = call_naver_api(core_keyword, naver_client_id, naver_client_secret)
        
        if encyc_results:
            for result in encyc_results[:max_count]:
                links.append({
                    "title": result.get('title', '').replace('<b>', '').replace('</b>', ''),
                    "url": result.get('link', ''),
                    "description": result.get('description', '')[:100].replace('<b>', '').replace('</b>', '') + '...',
                    "source": "naver_encyclopedia",
                    "keyword": core_keyword
                })
        else:
            # 검색 결과가 없는 경우
            keyword_encoded = urllib.parse.quote(core_keyword)
            links.append({
                "title": f"'{core_keyword}'에 대한 추가 정보",
                "url": f"https://terms.naver.com/search.naver?query={keyword_encoded}",
                "description": "네이버 지식백과에서 더 자세한 내용을 확인하세요.",
                "source": "naver_search",
                "keyword": core_keyword
            })
            
    except Exception as e:
        keyword_encoded = urllib.parse.quote(core_keyword)
        links.append({
            "title": f"네이버 지식백과에서 '{core_keyword}' 검색하기",
            "url": f"https://terms.naver.com/search.naver?query={keyword_encoded}",
            "description": "더 많은 정보를 찾아보세요.",
            "source": "naver_search",
            "keyword": core_keyword
        })
    
    return links


# ==================== 데이터 보강 함수들 ====================
def get_images(concept_ids: List[int], search_context: Dict[str, Any], supabase_client: Client, max_count: int = 1) -> List[Dict]:
    """검색 컨텍스트에 따른 이미지 조회"""
    images = []
    
    # 1. Dictionary가 주요 결과인 경우 - Dictionary 이미지 우선
    if search_context['primary_namespace'] == 'dictionary' and search_context['dictionary_words']:
        for word in search_context['dictionary_words'][:max_count]:
            try:
                response = supabase_client.table('dictionary').select("image_url, word").eq('word', word).execute()
                
                if response.data and response.data[0].get('image_url'):
                    images.append({
                        "url": response.data[0]['image_url'],
                        "description": f"{word} 관련 이미지",
                        "source": "dictionary"
                    })
            except Exception as e:
                pass
    
    # 2. FAQ가 주요 결과인 경우 - Chunk 이미지 우선 (chunk_concept_id 테이블)
    elif search_context['primary_namespace'] == 'faq' and concept_ids:
        for concept_id in concept_ids[:max_count]:
            try:
                # chunk_concept_id 테이블에서 이미지 조회
                response = supabase_client.table('chunk_concept_id').select("image_url").eq('concept_id', concept_id).limit(1).execute()
                
                if response.data and response.data[0].get('image_url'):
                    images.append({
                        "url": response.data[0]['image_url'],
                        "description": f"관련 교과서 이미지",
                        "source": "chunk"
                    })
            except Exception as e:
                pass
    
    # 3. 부족하면 Concept 이미지로 채우기
    remaining_count = max_count - len(images)
    if remaining_count > 0 and concept_ids:
        for concept_id in concept_ids[:remaining_count]:
            try:
                response = supabase_client.table('concept2').select("image_url, concept_name").eq('concept_id', concept_id).execute()
                
                if response.data and response.data[0].get('image_url'):
                    images.append({
                        "url": response.data[0]['image_url'],
                        "description": f"{response.data[0].get('concept_name', '개념')} 관련 이미지",
                        "source": "concept"
                    })
            except Exception as e:
                pass
    
    return images


def parse_choices(choice_text: str) -> List[str]:
    """선택지 텍스트 파싱"""
    if not choice_text:
        return []
    
    import re
    
    number_patterns = [
        r'^[①②③④⑤]\s*',
        r'^[\d]+\.\s*',
        r'^[\d]+\)\s*',
        r'^\([①②③④⑤]\)\s*',
        r'^\([\d]+\)\s*'
    ]
    
    choices = []
    lines = choice_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        cleaned_line = line
        for pattern in number_patterns:
            cleaned_line = re.sub(pattern, '', cleaned_line)
        
        if cleaned_line.strip():
            choices.append(cleaned_line.strip())
    
    # 한 줄에 모든 선택지가 있는 경우
    if len(choices) <= 1 and choice_text:
        text = choice_text
        for pattern in number_patterns:
            parts = re.split(pattern, text)
            if len(parts) > 1:
                choices = [part.strip() for part in parts if part.strip()]
                break
    
    return choices[:4]


def get_problems(concept_ids: List[int], supabase_client: Client, max_count: int = 2) -> Dict:
    """concept_id 기반 문제 조회 - paper_type 및 이미지 URL 포함"""
    problems = []
    
    if not concept_ids:
        return {
            "show_button": True,
            "button_text": "문제로 확인하기 📝",
            "items": problems
        }
    
    for concept_id in concept_ids:
        try:
            response = supabase_client.table('paper').select("*").eq('concept_id', concept_id).execute()
            
            if response.data:
                available_problems = response.data
                random.shuffle(available_problems)
                
                for problem_data in available_problems[:max_count - len(problems)]:
                    problem = {
                        "paper_id": problem_data.get('paper_id'),
                        "paper_type": problem_data.get('paper_type', ''),
                        "question": problem_data.get('question', ''),
                        "choices": parse_choices(problem_data.get('choice', '')),
                        "concept_id": concept_id,
                        "has_image": bool(problem_data.get('l_img_url')),
                        "l_img_url": problem_data.get('l_img_url') if problem_data.get('l_img_url') else None,
                        "c_img_url": problem_data.get('c_img_url') if problem_data.get('c_img_url') else None
                    }
                    problems.append(problem)
                    
                    if len(problems) >= max_count:
                        break
                        
        except Exception as e:
            pass
        
        if len(problems) >= max_count:
            break
    
    return {
        "show_button": True,
        "button_text": "문제로 확인하기 📝",
        "items": problems
    }


# ==================== HTML 템플릿 생성 ====================
def create_modern_html_template(response: Dict[str, Any]) -> str:
    """현대적이고 통일된 HTML 템플릿 생성"""
    
    html_body = format_as_html(response)
    
    template = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 학습 도우미 두리 - {response.get('query', '질문')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Malgun Gothic', sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            padding: 20px;
            line-height: 1.6;
            color: #333;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
            font-weight: 700;
        }}
        
        .header p {{
            opacity: 0.9;
            font-size: 16px;
        }}
        
        .content {{
            padding: 30px;
        }}
        
        .greeting {{
            background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            padding: 20px 30px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-size: 18px;
            font-weight: 500;
            color: #2d3748;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
        }}
        
        .section {{
            margin-bottom: 40px;
            background: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.05);
        }}
        
        .section h3 {{
            color: #667eea;
            font-size: 22px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 600;
        }}
        
        .main-concept {{
            background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 30px;
            box-shadow: 0 5px 20px rgba(252, 182, 159, 0.3);
        }}
        
        .main-concept h4 {{
            color: #2d3748;
            font-size: 18px;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        
        .main-concept p {{
            color: #4a5568;
            font-size: 16px;
            line-height: 1.8;
        }}
        
        .confidence-badge {{
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
            margin-top: 15px;
            background: rgba(255, 255, 255, 0.8);
            color: #667eea;
        }}
        
        .image-container {{
            text-align: center;
            margin: 20px 0;
        }}
        
        .image-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
            transition: transform 0.3s ease;
        }}
        
        .image-container img:hover {{
            transform: scale(1.02);
        }}
        
        .img-desc {{
            margin-top: 10px;
            color: #718096;
            font-size: 14px;
            font-style: italic;
        }}
        
        .link-item {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            border: 2px solid #e2e8f0;
            transition: all 0.3s ease;
        }}
        
        .link-item:hover {{
            border-color: #667eea;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.1);
        }}
        
        .link-item a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
            font-size: 16px;
        }}
        
        .link-desc {{
            color: #718096;
            margin-top: 8px;
            font-size: 14px;
        }}
        
        .problem-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 30px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.3);
            transition: all 0.3s ease;
            display: block;
            margin: 0 auto;
        }}
        
        .problem-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
        }}
        
        .problem-content {{
            display: none;
            margin-top: 20px;
        }}
        
        .problem-content.show {{
            display: block;
            animation: fadeIn 0.5s ease;
        }}
        
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        .problem-item {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            border: 2px solid #e2e8f0;
        }}
        
        .problem-item h5 {{
            color: #667eea;
            font-size: 18px;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        
        .problem-type {{
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 4px 12px;
            border-radius: 5px;
            font-size: 14px;
            margin-bottom: 10px;
        }}
        
        .problem-images {{
            margin: 15px 0;
        }}
        
        .problem-images img {{
            max-width: 100%;
            height: auto;
            border-radius: 10px;
            margin: 10px 0;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }}
        
        .problem-images .image-label {{
            font-size: 14px;
            color: #718096;
            margin-bottom: 5px;
            font-weight: 500;
        }}
        
        .problem-item ul {{
            list-style: none;
            margin-top: 15px;
        }}
        
        .problem-item li {{
            background: #f7fafc;
            padding: 12px 20px;
            margin-bottom: 8px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            transition: all 0.2s ease;
            cursor: pointer;
        }}
        
        .problem-item li:hover {{
            background: #edf2f7;
            border-color: #cbd5e0;
            transform: translateX(5px);
        }}
        
        .problem-item li::before {{
            content: "▶";
            color: #667eea;
            margin-right: 10px;
            font-size: 12px;
        }}
        
        .no-data {{
            text-align: center;
            color: #a0aec0;
            font-style: italic;
            padding: 20px;
        }}
        
        .footer {{
            background: #f7fafc;
            padding: 20px;
            text-align: center;
            color: #718096;
            font-size: 14px;
            border-top: 1px solid #e2e8f0;
        }}
        
        @media (max-width: 768px) {{
            .container {{
                margin: 10px;
                border-radius: 15px;
            }}
            
            .content {{
                padding: 20px;
            }}
            
            .header h1 {{
                font-size: 24px;
            }}
            
            .section {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌟 AI 학습 도우미 두리</h1>
            <p>초등학생을 위한 똑똑한 공부 친구</p>
        </div>
        
        <div class="content">
            {html_body}
        </div>
        
        <div class="footer">
            <p>생성 시간: {response.get('timestamp', '')}</p>
            <p>© 2024 AI 학습 도우미 두리</p>
        </div>
    </div>
    
    <script>
        // 문제 보기 버튼 기능
        document.addEventListener('DOMContentLoaded', function() {{
            const problemBtn = document.querySelector('.problem-btn');
            const problemContent = document.querySelector('.problem-content');
            
            if (problemBtn && problemContent) {{
                problemBtn.addEventListener('click', function() {{
                    problemContent.classList.toggle('show');
                    if (problemContent.classList.contains('show')) {{
                        problemBtn.textContent = '문제 숨기기 📕';
                    }} else {{
                        problemBtn.textContent = '문제로 확인하기 📝';
                    }}
                }});
            }}
        }});
    </script>
</body>
</html>
"""
    return template


# ==================== 응답 포맷팅 함수들 ====================
def format_as_html(response: Dict[str, Any]) -> str:
    """응답을 HTML 형식으로 변환 (개선된 버전)"""
    html = []
    
    # 인사말
    html.append(f'<div class="greeting">{response["greeting"]}</div>')
    
    # 메인 개념
    if response["main_concept"]["explanation"]:
        html.append('<div class="main-concept">')
        html.append(f'<h4>Q: {response["main_concept"].get("user_query", response["query"])}</h4>')
        html.append(f'<p>A: {response["main_concept"]["explanation"]}</p>')
        html.append(f'<span class="confidence-badge">신뢰도: {response.get("confidence", "unknown")}</span>')
        html.append('</div>')
    
    # 이미지
    if response["images"]:
        html.append('<div class="section">')
        html.append('<h3>🖼️ 관련 이미지</h3>')
        for img in response["images"]:
            html.append('<div class="image-container">')
            html.append(f'<img src="{img["url"]}" alt="{img["description"]}" />')
            html.append(f'<p class="img-desc">{img["description"]}</p>')
            html.append('</div>')
        html.append('</div>')
    
    # 관련 링크
    if response["related_links"]:
        html.append('<div class="section">')
        html.append('<h3>🔗 더 알아보기</h3>')
        for link in response["related_links"]:
            html.append(f'<div class="link-item">')
            html.append(f'<a href="{link["url"]}" target="_blank">{link["title"]}</a>')
            if link.get("description"):
                html.append(f'<p class="link-desc">{link["description"]}</p>')
            html.append(f'</div>')
        html.append('</div>')
    
    # 문제
    if response["problems"]["items"]:
        html.append('<div class="section">')
        html.append('<h3>✏️ 연습 문제</h3>')
        html.append(f'<button class="problem-btn">{response["problems"]["button_text"]}</button>')
        html.append('<div class="problem-content">')
        for i, problem in enumerate(response["problems"]["items"], 1):
            html.append(f'<div class="problem-item">')
            html.append(f'<h5>문제 {i}</h5>')
            
            # Paper type 표시
            if problem.get("paper_type"):
                html.append(f'<span class="problem-type">{problem["paper_type"]}</span>')
            
            html.append(f'<p>{problem["question"]}</p>')
            
            # 보기 이미지 (l_img_url)
            if problem.get("l_img_url"):
                html.append('<div class="problem-images">')
                html.append('<div class="image-label">보기 이미지:</div>')
                html.append(f'<img src="{problem["l_img_url"]}" alt="문제 보기 이미지" />')
                html.append('</div>')
            
            if problem["choices"]:
                html.append('<ul>')
                for choice in problem["choices"]:
                    html.append(f'<li>{choice}</li>')
                html.append('</ul>')
            
            # 선택지 이미지 (c_img_url)
            if problem.get("c_img_url"):
                html.append('<div class="problem-images">')
                html.append('<div class="image-label">선택지 이미지:</div>')
                html.append(f'<img src="{problem["c_img_url"]}" alt="선택지 이미지" />')
                html.append('</div>')
            
            html.append('</div>')
        html.append('</div>')
        html.append('</div>')
    
    return '\n'.join(html)


def format_as_text(response: Dict[str, Any]) -> str:
    """응답을 텍스트 형식으로 변환 (깔끔한 버전)"""
    lines = []
    
    # 인사말
    lines.append(response["greeting"])
    lines.append("")
    
    # 메인 개념
    if response["main_concept"]["explanation"]:
        lines.append("📖 핵심 설명")
        lines.append("-" * 50)
        lines.append(f"Q: {response['main_concept'].get('user_query', response['query'])}")
        lines.append(f"A: {response['main_concept']['explanation']}")
        lines.append(f"신뢰도: {response.get('confidence', 'unknown')}")
        lines.append("")
    
    # 이미지
    if response["images"]:
        lines.append("🖼️ 관련 이미지")
        lines.append("-" * 50)
        for i, img in enumerate(response["images"], 1):
            lines.append(f"{i}. {img['description']} ({img['source']})")
            lines.append(f"   URL: {img['url']}")
        lines.append("")
    
    # 관련 링크
    if response["related_links"]:
        lines.append("🔗 더 알아보기")
        lines.append("-" * 50)
        for i, link in enumerate(response["related_links"], 1):
            if link.get('keyword'):
                lines.append(f"{i}. [{link['keyword']}] {link['title']}")
            else:
                lines.append(f"{i}. {link['title']}")
            if link.get('description'):
                lines.append(f"   {link['description']}")
            lines.append(f"   URL: {link['url']}")
        lines.append("")
    
    # 문제
    if response["problems"]["items"]:
        lines.append("✏️ 연습 문제")
        lines.append("-" * 50)
        lines.append(f"[{response['problems']['button_text']}]")
        lines.append("")
        for i, problem in enumerate(response["problems"]["items"], 1):
            lines.append(f"문제 {i}: {problem['question']}")
            if problem.get('paper_type'):
                lines.append(f"유형: {problem['paper_type']}")
            if problem.get('l_img_url'):
                lines.append(f"보기 이미지: {problem['l_img_url']}")
            if problem['choices']:
                for j, choice in enumerate(problem['choices'], 1):
                    lines.append(f"  {j}. {choice}")
            if problem.get('c_img_url'):
                lines.append(f"선택지 이미지: {problem['c_img_url']}")
            lines.append("")
    
    lines.append("")
    lines.append(f"⏱️ 응답 시간: {response.get('execution_time', 0):.2f}초")
    
    if response.get('concept_ids'):
        lines.append(f"📌 관련 concept_id: {response['concept_ids']}")
    
    return '\n'.join(lines)


# ==================== 메인 클래스 ====================
class StudentFriendlyFormatter:
    """학생 친화적 응답 포매터"""
    
    def __init__(self, custom_config: Dict[str, Any] = None):
        """초기화"""
        self.config = get_default_config()
        if custom_config:
            self.config.update(custom_config)
        
        # 출력 억제하면서 초기화
        with suppress_output():
            # 모듈 초기화
            self.search_module = SearchModule()
            self.supabase = create_client(
                os.getenv('SUPABASE_URL'),
                os.getenv('SUPABASE_SERVICE_KEY')
            )
        
        # 네이버 API 설정
        self.naver_client_id = os.getenv('NAVER_CLIENT_ID')
        self.naver_client_secret = os.getenv('NAVER_CLIENT_SECRET')
    
    def search_and_format(self, query: str) -> Dict[str, Any]:
        """검색 실행 후 학생 친화적으로 포맷팅"""
        try:
            # 간단한 진행 표시
            print(f"\n🔍 '{query}'에 대해 검색 중...")
            print("📚 자료를 분석하고 있어요...")
            
            # 1. 검색 실행 (모든 출력 억제)
            search_results = self.search_module.search(query)
            
            # 2. concept_ids와 검색 컨텍스트 추출
            concept_ids = extract_concept_ids(search_results)
            search_context = extract_search_context(search_results)
            
            # 3. 메인 컨셉 추출
            main_concept = extract_main_concept(
                search_results, 
                self.config["main_concept"]["max_chars"]
            )
            
            # 4. 추가 데이터 수집
            print("🖼️ 관련 자료를 수집하고 있어요...")
            
            images = get_images(
                concept_ids,
                search_context,
                self.supabase,
                self.config["images"]["max_count"]
            )
            
            related_links = get_related_links(
                query, 
                concept_ids,
                self.supabase,
                self.naver_client_id,
                self.naver_client_secret,
                self.config["related_links"]["max_count"]
            )
            
            problems = get_problems(
                concept_ids,
                self.supabase,
                self.config["problems"]["max_count"]
            )
            
            print("✨ 답변 준비 완료!")
            
            # 5. 응답 구성
            formatted_response = {
                "query": query,
                "greeting": self.config["greeting"],
                "main_concept": main_concept,
                "images": images,
                "related_links": related_links,
                "problems": problems,
                "execution_time": search_results.get('execution_time', 0),
                "concept_ids": concept_ids,
                "dictionary_words": search_context.get('dictionary_words', []),
                "confidence": search_results.get('confidence', 'unknown'),
                "timestamp": datetime.now().isoformat()
            }
            
            return formatted_response
            
        except Exception as e:
            return self._build_error_response(query, str(e))
    
    def _build_error_response(self, query: str, error_msg: str) -> Dict[str, Any]:
        """오류 응답 구성"""
        return {
            "query": query,
            "greeting": self.config["greeting"],
            "error": error_msg,
            "main_concept": {
                "title": "오류 발생",
                "explanation": "죄송해요, 답변을 만드는 중에 문제가 생겼어요.",
                "source": "error"
            },
            "images": [],
            "related_links": [],
            "problems": {"items": []},
            "timestamp": datetime.now().isoformat()
        }
    
    def format_as_html(self, response: Dict[str, Any]) -> str:
        """HTML 형식으로 변환"""
        return format_as_html(response)
    
    def format_as_text(self, response: Dict[str, Any]) -> str:
        """텍스트 형식으로 변환"""
        return format_as_text(response)
    
    def format_as_json(self, response: Dict[str, Any]) -> str:
        """JSON 형식으로 변환"""
        return json.dumps(response, ensure_ascii=False, indent=2)


# ==================== 대화형 테스트 함수 ====================
def interactive_test():
    """대화형 응답 포맷터 테스트"""
    
    # 초기화 시 출력 억제
    print("\n🌟 AI 학습 도우미 두리를 시작하는 중...")
    formatter = StudentFriendlyFormatter()
    
    print("\n" + "="*60)
    print("🌟 AI 학습 도우미 두리에 오신 것을 환영합니다! 🌟")
    print("="*60)
    print("질문을 입력하세요. (종료: quit)")
    print("예시: 고조선은 어떻게 만들어졌어?")
    print("="*60)
    
    while True:
        # 사용자 입력
        query = input("\n💬 질문: ").strip()
        
        # 종료 조건
        if query.lower() in ['quit', 'exit', '종료', '그만']:
            print("\n👋 안녕히 가세요! 다음에 또 만나요!")
            break
        
        # 빈 입력 처리
        if not query:
            print("❗ 질문을 입력해주세요!")
            continue
        
        try:
            # 검색 및 포맷팅
            response = formatter.search_and_format(query)
            
            print("\n" + "="*60)
            # 텍스트 형식으로 출력
            formatted_text = formatter.format_as_text(response)
            print(formatted_text)
            
            # HTML 저장 옵션
            save = input("\n📄 HTML 파일로 저장하시겠습니까? (y/n): ").lower()
            if save == 'y':
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"response_{timestamp}.html"
                
                html_content = create_modern_html_template(response)
                
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"✅ 저장 완료: {filename}")
                
        except Exception as e:
            print(f"\n❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()
            print("다시 시도해주세요.")


# ==================== 메인 실행 ====================
if __name__ == "__main__":
    # 대화형 모드로 실행
    interactive_test()
