import yfinance as yf
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from stocks.models import PredictionLog

class Command(BaseCommand):
    help = '과거 AI 예측 로그의 실제 성과(등락률, 성공 여부)를 일괄 업데이트합니다.'

    def handle(self, *args, **options):
        logs_to_evaluate = PredictionLog.objects.filter(is_correct__isnull=True).order_by('prediction_date')
        total_count = logs_to_evaluate.count()

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("평가할 예측 로그가 없습니다."))
            return

        self.stdout.write(self.style.NOTICE(f"총 {total_count}개의 로그를 평가하기 시작합니다..."))

        success_count = 0
        fail_count = 0

        for i, log in enumerate(logs_to_evaluate):
            try:
                start_date = log.prediction_date
                end_date = start_date + timedelta(days=7) # 주말 포함 넉넉하게 7일로 변경
                
                self.stdout.write(f"[{i+1}/{total_count}] {log.stock.code} ({start_date}) 분석 중...", ending="\r")
                
                # 데이터 다운로드
                data = yf.download(log.stock.code, start=start_date, end=end_date, progress=False)

                # 1. 데이터 검증 (최소 2거래일 데이터 필요: 당일, 다음날)
                if data.empty or len(data) < 2:
                    self.stdout.write(f"데이터 부족으로 스킵: {log.stock.code} (행 개수: {len(data)})")
                    continue

                try:
                    # [수정 핵심] .values 대신 .iloc를 사용하여 정확한 행에 접근합니다.
                    # yfinance 데이터는 DataFrame 형태이며, iloc[0]이 start_date(t), iloc[1]이 다음 영업일(t+1)입니다.
                    
                    # 'Close' 컬럼만 추출
                    close_data = data['Close']
                    
                    # 혹시 모를 MultiIndex 컬럼 문제 방지 (yfinance 버전에 따라 다를 수 있음)
                    # 만약 컬럼이 ('Close', 'NVDA') 처럼 되어있을 경우를 대비해 squeeze() 등을 쓸 수도 있으나,
                    # 일반적으로 단일 종목 download시에는 iloc로 접근하면 안전합니다.
                    
                    # 스칼라 값(하나의 숫자)으로 명확히 변환 (.item() 사용 권장)
                    price_t = float(close_data.iloc[0].item()) if hasattr(close_data.iloc[0], 'item') else float(close_data.iloc[0])
                    price_t1 = float(close_data.iloc[1].item()) if hasattr(close_data.iloc[1], 'item') else float(close_data.iloc[1])

                    # 등락률 계산
                    actual_change = (price_t1 - price_t) / price_t * 100

                    # 4. 실제 결과 정의
                    if actual_change > 0.5:
                        actual_outcome = "상승"
                    elif actual_change < -0.5:
                        actual_outcome = "하락"
                    else:
                        actual_outcome = "보합"

                    # 5. 예측 성공 여부 판단
                    is_correct = False
                    predicted_signal = log.predicted_signal

                    if '매수' in predicted_signal and actual_outcome in ["상승", "보합"]:
                        is_correct = True
                    elif '매도' in predicted_signal and actual_outcome in ["하락", "보합"]:
                        is_correct = True
                    elif '관망' in predicted_signal and actual_outcome == "보합":
                        is_correct = True

                    # 6. 모델 업데이트
                    log.actual_outcome = actual_outcome
                    log.actual_change_percent = actual_change
                    log.is_correct = is_correct
                    log.evaluated_at = timezone.now()
                    log.save()
                    
                    success_count += 1

                except Exception as inner_e:
                    # 데이터 파싱 중 에러 상세 출력
                    self.stdout.write(self.style.ERROR(f"\n{log.stock.code} 데이터 처리 오류: {inner_e}"))
                    fail_count += 1
                    continue

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\n{log.stock.code} 다운로드/시스템 오류: {e}"))
                fail_count += 1

        self.stdout.write("\n" + "="*40)
        self.stdout.write(self.style.SUCCESS(f"작업 완료!"))
        self.stdout.write(f"- 업데이트 성공: {success_count}건")
        self.stdout.write(f"- 실패/데이터부족: {fail_count}건")
        self.stdout.write("="*40)