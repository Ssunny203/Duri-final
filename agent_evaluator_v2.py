"""
RAG 평가 시스템 - 간소화 버전 (사실 확인형 특화)
"""

import os
import time
import re
from typing import List, Dict, Any, Tuple
from datetime import datetime
from dotenv import load_dotenv

from response_formatter_v4 import StudentFriendlyFormatter

load_dotenv()


class SimplifiedRAGEvaluator:
    """간소화된 사실 확인형 RAG 평가기"""
    
    def __init__(self):
        """초기화"""
        print("🔧 평가 시스템 초기화 중...")
        self.formatter = StudentFriendlyFormatter()
        
        # 사실 확인형 평가 가중치
        self.weights = {
            "retrieval": {
                "keyword_found": 0.4,      # 키워드 발견률
                "source_quality": 0.3,     # 소스 품질
                "information_density": 0.3  # 정보 밀도
            },
            "generation": {
                "fact_accuracy": 0.5,      # 사실 정확도
                "completeness": 0.3,       # 완전성
                "clarity": 0.2            # 명확성
            },
            "overall": {
                "retrieval": 0.4,
                "generation": 0.5,
                "speed": 0.1
            }
        }
        
        print("✅ 시스템 준비 완료!")
    
    def extract_keywords_from_question(self, question: str) -> List[str]:
        """질문에서 자동으로 핵심 키워드 추출"""
        # 조사 제거
        particles = ['은', '는', '이', '가', '을', '를', '에', '에서', '으로', 
                    '와', '과', '의', '로', '이란', '란', '에게', '한테', '께']
        
        # 의문사 제거
        question_words = ['누구', '언제', '어디', '무엇', '뭐', '왜', '어떻게', 
                         '얼마나', '몇', '어느', '어떤']
        
        # 동사 어미 제거
        verb_endings = ['야', '이야', '예요', '이에요', '습니까', '습니다', 
                       '어요', '아요', '죠', '지', '했어', '됐어', '였어']
        
        words = question.split()
        keywords = []
        
        for word in words:
            # 물음표 제거
            word = word.replace('?', '')
            
            # 의문사는 제외
            if word in question_words:
                continue
            
            # 조사 제거
            for particle in particles:
                if word.endswith(particle) and len(word) > len(particle):
                    word = word[:-len(particle)]
                    break
            
            # 동사 어미 제거
            for ending in verb_endings:
                if word.endswith(ending) and len(word) > len(ending):
                    word = word[:-len(ending)]
                    break
            
            # 2글자 이상인 명사형 단어만 추가
            if len(word) >= 2 and not any(word.endswith(v) for v in ['하다', '되다', '하기', '되기']):
                keywords.append(word)
        
        # 중복 제거하고 중요도순 정렬 (긴 단어가 더 중요)
        keywords = list(dict.fromkeys(keywords))  # 순서 유지하며 중복 제거
        keywords.sort(key=len, reverse=True)
        
        return keywords[:5]  # 최대 5개 키워드
    
    def evaluate_question(self, question: str) -> Dict[str, Any]:
        """단일 질문 평가 (간소화)"""
        # 1. 키워드 자동 추출
        keywords = self.extract_keywords_from_question(question)
        
        # 2. RAG 실행
        start_time = time.time()
        response = self.formatter.search_and_format(question)
        execution_time = time.time() - start_time
        
        # 3. 생성된 답변
        answer = response.get("main_concept", {}).get("explanation", "")
        
        # 4. 평가 수행
        
        # Retrieval 평가
        retrieval_score = self._evaluate_retrieval(response, keywords)
        
        # Generation 평가
        generation_score = self._evaluate_generation(answer, keywords, question)
        
        # Speed 평가
        speed_score = 1.0 if execution_time < 3 else (0.7 if execution_time < 5 else 0.4)
        
        # 종합 점수
        overall_score = (
            retrieval_score * self.weights["overall"]["retrieval"] +
            generation_score * self.weights["overall"]["generation"] +
            speed_score * self.weights["overall"]["speed"]
        )
        
        # 등급
        grade = self._get_grade(overall_score)
        
        # 결과 구성
        result = {
            "question": question,
            "keywords": keywords,
            "answer": answer,
            "scores": {
                "retrieval": retrieval_score,
                "generation": generation_score,
                "speed": speed_score,
                "overall": overall_score
            },
            "grade": grade,
            "execution_time": execution_time,
            "confidence": response.get("confidence", "unknown")
        }
        
        # 결과 출력
        self._print_result(result)
        
        return result
    
    def _evaluate_retrieval(self, response: Dict[str, Any], keywords: List[str]) -> float:
        """검색 평가 (사실 확인형)"""
        scores = {}
        
        # 1. 키워드 발견률
        answer = response.get("main_concept", {}).get("explanation", "").lower()
        found_keywords = sum(1 for kw in keywords if kw.lower() in answer)
        scores["keyword_found"] = found_keywords / len(keywords) if keywords else 0.5
        
        # 2. 소스 품질 (신뢰도 기반)
        confidence_map = {"high": 1.0, "medium": 0.7, "low": 0.4, "very_low": 0.2}
        scores["source_quality"] = confidence_map.get(response.get("confidence", "medium"), 0.5)
        
        # 3. 정보 밀도 (추가 자료 유무)
        info_density = 0.0
        if response.get("images"):
            info_density += 0.33
        if response.get("related_links"):
            info_density += 0.33
        if response.get("problems", {}).get("items"):
            info_density += 0.34
        scores["information_density"] = info_density
        
        # 가중 평균
        return sum(scores[k] * self.weights["retrieval"][k] for k in scores)
    
    def _evaluate_generation(self, answer: str, keywords: List[str], question: str) -> float:
        """생성 평가 (사실 확인형)"""
        scores = {}
        
        # 1. 사실 정확도 (키워드 포함 + 숫자/날짜 포함)
        keyword_score = sum(1 for kw in keywords if kw.lower() in answer.lower()) / len(keywords) if keywords else 0.5
        has_numbers = bool(re.search(r'\d+', answer))
        has_specific_info = any(term in answer for term in ['년', '세기', '왕', '시대'])
        
        scores["fact_accuracy"] = keyword_score * 0.6
        if has_numbers:
            scores["fact_accuracy"] += 0.2
        if has_specific_info:
            scores["fact_accuracy"] += 0.2
        scores["fact_accuracy"] = min(scores["fact_accuracy"], 1.0)
        
        # 2. 완전성 (질문 유형에 따른 답변)
        scores["completeness"] = 0.5
        if "언제" in question and has_numbers:
            scores["completeness"] = 0.9
        elif "누구" in question and any(name in answer for name in keywords):
            scores["completeness"] = 0.9
        elif "무엇" in question or "뭐" in question:
            scores["completeness"] = 0.8 if len(answer) > 50 else 0.6
        elif len(answer) > 80:
            scores["completeness"] = 0.8
        
        # 3. 명확성 (간결하고 직접적인 답변)
        scores["clarity"] = 1.0
        if len(answer) > 150:
            scores["clarity"] -= 0.2
        if not answer.endswith(('.', '요', '다', '야')):
            scores["clarity"] -= 0.1
        if answer.count(',') > 5:  # 너무 복잡한 문장
            scores["clarity"] -= 0.1
        scores["clarity"] = max(scores["clarity"], 0.0)
        
        # 가중 평균
        return sum(scores[k] * self.weights["generation"][k] for k in scores)
    
    def _get_grade(self, score: float) -> str:
        """점수를 등급으로 변환"""
        if score >= 0.8:
            return "A (탁월)"
        elif score >= 0.7:
            return "B (양호)"
        elif score >= 0.6:
            return "C (보통)"
        elif score >= 0.5:
            return "D (미흡)"
        else:
            return "F (부족)"
    
    def _print_result(self, result: Dict[str, Any]):
        """결과 출력"""
        print(f"\n{'='*50}")
        print(f"📊 평가 결과")
        print(f"{'='*50}")
        print(f"🔑 키워드: {', '.join(result['keywords'])}")
        print(f"📈 점수:")
        print(f"   검색: {result['scores']['retrieval']:.2f}")
        print(f"   생성: {result['scores']['generation']:.2f}")
        print(f"   속도: {result['scores']['speed']:.2f}")
        print(f"🏆 종합: {result['scores']['overall']:.2f} - {result['grade']}")
        print(f"{'='*50}")


def main():
    """메인 실행"""
    print("\n🎯 RAG 평가 시스템 (간소화)")
    print("="*50)
    
    evaluator = SimplifiedRAGEvaluator()
    
    while True:
        print("\n1. 새 질문 평가")
        print("2. 빠른 평가 (연속)")
        print("3. 종료")
        
        choice = input("\n선택 (1-3): ").strip()
        
        if choice == "1":
            question = input("\n질문: ").strip()
            if question:
                evaluator.evaluate_question(question)
        
        elif choice == "2":
            print("\n연속 평가 모드 (빈 줄 입력시 종료)")
            while True:
                question = input("\n질문: ").strip()
                if not question:
                    break
                evaluator.evaluate_question(question)
        
        elif choice == "3":
            print("\n👋 종료합니다.")
            break


if __name__ == "__main__":
    main()