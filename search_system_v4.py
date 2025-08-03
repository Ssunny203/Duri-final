import os
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from openai import OpenAI
from pinecone import Pinecone
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict

# 환경 변수 로드
load_dotenv()

class FlexibleSearchSystem:
    def __init__(self):
        # API 클라이언트 초기화
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
        self.supabase: Client = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_KEY')
        )
        
        # 인덱스 연결
        self.index_name = os.getenv('PINECONE_INDEX_NAME', 'socialagent3-vectors')
        self.index = self.pc.Index(self.index_name)
        
        # 임베딩 모델 설정
        self.embedding_model = "text-embedding-3-large"
        
        # 네임스페이스별 설정 (가중치, 검색 개수)
        self.namespace_configs = {
            'faq': {'weight': 1.2, 'top_k': 3, 'description': 'FAQ'},
            'dictionary': {'weight': 1.0, 'top_k': 2, 'description': '용어사전'},
            'concept': {'weight': 0.9, 'top_k': 2, 'description': '개념설명'},
            'chunk': {'weight': 0.8, 'top_k': 2, 'description': '교과서'}
        }
        
        # 로깅 대신 간단한 출력 (필요시 제거 가능)
        # print("유연한 검색 시스템 초기화 완료")
    
    def create_query_embedding(self, query: str) -> List[float]:
        """검색 쿼리를 임베딩으로 변환"""
        try:
            # 검색 키워드 분석 (출력 제거 가능)
            # words = query.split()
            # print(f"검색 키워드: {words}")
            
            response = self.openai_client.embeddings.create(
                input=query,
                model=self.embedding_model,
                dimensions=1024
            )
            return response.data[0].embedding
        except Exception as e:
            # print(f"쿼리 임베딩 생성 실패: {e}")
            raise
    
    def search_all_namespaces(self, query_embedding: List[float]) -> List[Dict]:
        """모든 네임스페이스에서 병렬 검색"""
        all_results = []
        
        for namespace, config in self.namespace_configs.items():
            try:
                response = self.index.query(
                    vector=query_embedding,
                    top_k=config['top_k'],
                    namespace=namespace,
                    include_metadata=True
                )
                
                for match in response['matches']:
                    result = {
                        'id': match['id'],
                        'score': match['score'],
                        'weighted_score': match['score'] * config['weight'],
                        'namespace': namespace,
                        'namespace_desc': config['description'],
                        'metadata': match['metadata']
                    }
                    all_results.append(result)
                
            except Exception as e:
                # print(f"{namespace} 검색 중 오류: {e}")
                continue
        
        # 가중치 적용 점수로 정렬
        all_results.sort(key=lambda x: x['weighted_score'], reverse=True)
        
        return all_results
    
    def calculate_confidence_level(self, results: List[Dict]) -> Tuple[str, float]:
        """검색 결과의 신뢰도 계산"""
        if not results:
            return 'none', 0.0
        
        best_score = results[0]['weighted_score']
        
        # 절대적 점수 기준
        if best_score >= 0.8:
            confidence = 'high'
        elif best_score >= 0.6:
            confidence = 'medium'
        elif best_score >= 0.4:
            confidence = 'low'
        else:
            confidence = 'very_low'
        
        # 상위 결과들의 점수 분포도 고려
        if len(results) >= 2:
            score_variance = np.std([r['weighted_score'] for r in results[:3]])
            if score_variance < 0.1:  # 상위 결과들이 비슷한 점수
                confidence_score = best_score + 0.05
            else:
                confidence_score = best_score
        else:
            confidence_score = best_score
        
        return confidence, confidence_score
    
    def select_diverse_results(self, results: List[Dict], max_results: int = 3) -> List[Dict]:
        """다양한 네임스페이스에서 결과 선택"""
        if not results:
            return []
        
        selected = []
        namespace_count = defaultdict(int)
        
        # 최고 점수 결과는 무조건 포함
        best_result = results[0]
        selected.append(best_result)
        namespace_count[best_result['namespace']] += 1
        
        # 최고 점수의 80% 이상인 결과들 중에서 선택
        threshold = best_result['weighted_score'] * 0.8
        candidates = [r for r in results[1:] if r['weighted_score'] >= threshold]
        
        # 다양성을 고려하여 추가 선택
        for result in candidates:
            if len(selected) >= max_results:
                break
            
            # 같은 네임스페이스에서 2개 이상 선택하지 않음
            if namespace_count[result['namespace']] < 2:
                selected.append(result)
                namespace_count[result['namespace']] += 1
        
        # 부족하면 점수순으로 채움
        if len(selected) < max_results:
            remaining = [r for r in results if r not in selected]
            selected.extend(remaining[:max_results - len(selected)])
        
        return selected[:max_results]
    
    def get_concept_by_id(self, concept_id: int) -> Optional[Dict]:
        """concept_id로 개념 정보 조회"""
        try:
            concept_id = int(concept_id)  # float to int 변환
            response = self.supabase.table('concept2').select("*").eq('concept_id', concept_id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            # print(f"Concept 조회 중 오류: {e}")
            return None
    
    def extract_content_from_result(self, result: Dict) -> Dict[str, Any]:
        """검색 결과에서 내용 추출"""
        namespace = result['namespace']
        metadata = result['metadata']
        content = {
            'namespace': namespace,
            'score': result['score'],
            'weighted_score': result['weighted_score']
        }
        
        if namespace == 'faq':
            content['question'] = metadata.get('question', '')
            content['answer'] = metadata.get('answer', '')
            content['concept_id'] = metadata.get('concept_id')
            
        elif namespace == 'dictionary':
            content['word'] = metadata.get('word', '')
            content['explanation'] = metadata.get('word_explanation', '')
            content['concept_id'] = metadata.get('concept_id')
            
        elif namespace == 'concept':
            content['concept_name'] = metadata.get('concept_name', '')
            content['summary'] = metadata.get('summary_text', '')
            content['full_description'] = metadata.get('full_description', '')
            
        elif namespace == 'chunk':
            content['text'] = metadata.get('chunk_text', '')
            content['concept_id'] = metadata.get('concept_id')
        
        # concept_id가 있으면 추가 정보 조회
        if content.get('concept_id'):
            concept = self.get_concept_by_id(content['concept_id'])
            if concept:
                content['related_concept'] = {
                    'name': concept.get('concept_name', ''),
                    'summary': concept.get('summary_text', '')
                }
        
        return content
    
    def generate_composite_answer(self, query: str, results: List[Dict], confidence: str) -> str:
        """여러 소스를 통합한 자연스러운 답변 생성"""
        try:
            # 각 결과에서 내용 추출
            contents = [self.extract_content_from_result(r) for r in results]
            
            # 프롬프트 구성
            system_prompt = """당신은 초등학생을 가르치는 친절한 선생님입니다.
            여러 자료를 참고하여 학생의 질문에 통합적이고 자연스러운 답변을 만들어주세요.
            어려운 용어는 쉽게 풀어서 설명하고, 친근한 말투를 사용하세요."""
            
            # 주요 정보와 보조 정보 구분
            primary_content = contents[0] if contents else {}
            supplementary_contents = contents[1:] if len(contents) > 1 else []
            
            user_prompt = f"""
            학생 질문: {query}
            
            주요 정보 (신뢰도: {results[0]['weighted_score']:.2f}):
            출처: {primary_content.get('namespace', '')}
            내용: {self._format_content(primary_content)}
            
            추가 참고 정보:
            {self._format_supplementary(supplementary_contents)}
            
            신뢰도 수준: {confidence}
            
            위 정보들을 자연스럽게 통합하여 답변해주세요.
            신뢰도가 낮은 경우 조심스럽게 표현하고, 높은 경우 확신있게 설명해주세요.
            """
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=600
            )
            
            answer = response.choices[0].message.content
            
            # 신뢰도에 따른 추가 메시지
            confidence_messages = {
                'very_low': "\n\n💭 참고로 이 답변은 관련 정보가 부족해서 정확하지 않을 수 있어요. 선생님께 확인해보는 것이 좋겠어요!",
                'low': "\n\n💡 이 정보가 도움이 되었으면 좋겠어요. 더 궁금한 점이 있다면 선생님께 물어보세요!",
                'medium': "",
                'high': ""
            }
            
            return answer + confidence_messages.get(confidence, "")
            
        except Exception as e:
            # print(f"답변 생성 중 오류: {e}")
            return "답변을 생성하는 중에 문제가 발생했어요. 다시 시도해주세요."
    
    def _format_content(self, content: Dict) -> str:
        """내용을 문자열로 포맷팅"""
        namespace = content.get('namespace', '')
        
        if namespace == 'faq':
            return f"Q: {content.get('question', '')}\nA: {content.get('answer', '')}"
        elif namespace == 'dictionary':
            return f"{content.get('word', '')}: {content.get('explanation', '')}"
        elif namespace == 'concept':
            return f"{content.get('concept_name', '')}: {content.get('summary', '')}"
        elif namespace == 'chunk':
            return content.get('text', '')
        
        return str(content)
    
    def _format_supplementary(self, contents: List[Dict]) -> str:
        """보조 정보 포맷팅"""
        if not contents:
            return "없음"
        
        formatted = []
        for i, content in enumerate(contents):
            formatted.append(f"{i+1}. [{content.get('namespace', '')}] {self._format_content(content)[:200]}...")
        
        return "\n".join(formatted)
    
    def search_and_answer(self, query: str) -> Dict[str, Any]:
        """통합 검색 및 답변 생성"""
        start_time = datetime.now()
        
        # 검색어 분석 표시 (화면에도 출력) - 필요시 제거 가능
        print(f"\n검색어: '{query}'")
        words = query.split()
        print(f"검색 키워드: {words}")
        print("-" * 40)
        
        # 1. 쿼리 임베딩 생성
        query_embedding = self.create_query_embedding(query)
        
        # 2. 모든 네임스페이스에서 병렬 검색
        all_results = self.search_all_namespaces(query_embedding)
        
        if not all_results:
            return {
                'query': query,
                'answer': "관련 정보를 찾을 수 없어요. 다른 질문을 해보시거나 선생님께 여쭤보세요.",
                'confidence': 'none',
                'confidence_score': 0,
                'results': [],
                'execution_time': (datetime.now() - start_time).total_seconds()
            }
        
        # 3. 신뢰도 계산
        confidence, confidence_score = self.calculate_confidence_level(all_results)
        
        # 4. 다양한 소스에서 결과 선택
        selected_results = self.select_diverse_results(all_results, max_results=3)
        
        # 5. 통합 답변 생성
        answer = self.generate_composite_answer(query, selected_results, confidence)
        
        # 실행 시간 계산
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'query': query,
            'answer': answer,
            'confidence': confidence,
            'confidence_score': confidence_score,
            'results': selected_results,
            'sources': [r['namespace_desc'] for r in selected_results],
            'execution_time': execution_time
        }
    
    def format_answer_response(self, response: Dict[str, Any]) -> str:
        """답변 결과를 읽기 쉬운 형태로 포맷팅"""
        output = []
        output.append(f"\n🔍 질문: '{response['query']}'")
        output.append(f"📊 신뢰도: {response['confidence']} ({response['confidence_score']:.3f})")
        output.append(f"📚 참고 자료: {', '.join(response.get('sources', []))}")
        output.append(f"⏱️ 응답 시간: {response['execution_time']:.2f}초")
        output.append("\n" + "="*60 + "\n")
        output.append("💬 답변:")
        output.append(response['answer'])
        
        return "\n".join(output)

# 대화형 검색 함수
def interactive_search():
    """대화형 검색 시스템"""
    searcher = FlexibleSearchSystem()
    
    print("\n🎓 스마트 학습 도우미 v4에 오신 것을 환영합니다!")
    print("궁금한 것을 물어보세요. (종료: 'exit', 'quit', '종료')")
    print("="*60)
    
    while True:
        try:
            # 사용자 입력 받기
            query = input("\n❓ 질문: ").strip()
            
            # 종료 명령 확인
            if query.lower() in ['exit', 'quit', '종료', 'q']:
                print("\n👋 안녕히 가세요! 다음에 또 만나요!")
                break
            
            # 빈 입력 처리
            if not query:
                print("💭 질문을 입력해주세요!")
                continue
            
            # 검색 실행
            print("\n🔍 검색 중...")
            response = searcher.search_and_answer(query)
            formatted = searcher.format_answer_response(response)
            print(formatted)
            
        except KeyboardInterrupt:
            print("\n\n👋 프로그램을 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ 오류가 발생했습니다: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    interactive_search()
