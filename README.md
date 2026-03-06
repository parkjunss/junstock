# Stock App Backend

Django 기반의 주식 분석 및 포트폴리오 관리 애플리케이션을 위한 백엔드 서버입니다. 사용자 관리, 관심 종목, 주식 데이터, AI 리포트 등 다양한 기능을 위한 API를 제공합니다.

## 주요 기능

*   **사용자 인증**: Django Allauth를 사용한 로컬 및 소셜 계정(Google) 인증 시스템.
*   **주식 정보**: `yfinance` 및 `finviz` 라이브러리를 활용하여 주식의 현재가, 시가총액, PER, PBR 등 다양한 지표를 제공.
*   **관심 종목**: 사용자가 관심 있는 주식을 등록하고 관리.
*   **AI 리포트**: Google Gemini API를 사용하여 특정 주식에 대한 AI 기반 분석 리포트를 생성.
*   **재무 데이터**: 정기적인 Celery 작업을 통해 재무제표 데이터를 수집하고 저장.
*   **푸시 알림**: Firebase Cloud Messaging (FCM)을 통한 실시간 알림 기능.
*   **포트폴리오 관리**: 사용자가 자신의 주식 보유 현황을 추적하고 관리.
*   **뉴스 및 공시**: 주식과 관련된 최신 뉴스와 공시 정보 제공.
*   **스크리너**: 다양한 조건으로 원하는 주식을 필터링하는 기능.
*   **마켓 데이터**: S&P 500 등 주요 시장 지수 및 공포-탐욕 지수 추적.

## 기술 스택

*   **백엔드**: Python, Django, Django REST Framework
*   **데이터베이스**: SQLite3 (기본 설정)
*   **비동기 작업**: Celery, Redis
*   **인증**: `dj-rest-auth`, `django-allauth`
*   **데이터 수집**: `yfinance`, `finvizfinance`, `beautifulsoup4`
*   **AI**: `google-generativeai`
*   **알림**: `fcm-django`
*   **패키지 관리**: `uv`

## 설정 및 실행 방법

1.  **저장소 복제**:
    ```bash
    git clone <repository-url>
    cd stock_app_backend
    ```

2.  **Python 가상환경 생성 및 활성화**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate
    ```

3.  **의존성 설치**:
    `uv`를 사용하여 `pyproject.toml`에 명시된 의존성을 설치합니다.
    ```bash
    pip install uv
    uv pip install -r requirements.txt  # 혹은 pyproject.toml 기반으로 설치
    ```

4.  **환경 변수 설정**:
    `.env` 파일을 생성하고 아래와 같이 필요한 환경 변수를 설정합니다.
    ```
    SECRET_KEY='your-django-secret-key'
    GEMINI_API_KEY='your-gemini-api-key'
    ```
    `fcm-service-account-key.json` 파일도 프로젝트 루트에 위치시켜야 합니다.

5.  **데이터베이스 마이그레이션**:
    ```bash
    python manage.py migrate
    ```

6.  **초기 데이터 임포트 (선택 사항)**:
    필요한 초기 데이터를 로드하기 위해 아래의 관리자 명령어를 실행할 수 있습니다.
    ```bash
    python manage.py import_stocks
    python manage.py update_sp500_status
    python manage.py get_subjects
    ```

7.  **개발 서버 실행**:
    ```bash
    python manage.py runserver
    ```

8.  **Celery 워커 실행** (별도의 터미널에서):
    ```bash
    celery -A config worker -l info -P eventlet
    ```

## 프로젝트 구조

```
E:/stock_app_backend/
├── config/          # Django 프로젝트 설정 (settings, urls 등)
├── stocks/          # 핵심 애플리케이션
│   ├── models.py    # 데이터 모델 정의
│   ├── views.py     # API 뷰
│   ├── serializers.py # 데이터 직렬화
│   ├── urls.py      # 앱 URL 라우팅
│   ├── tasks.py     # Celery 비동기 작업
│   └── management/  # 관리자 명령어
│       └── commands/
├── main.py          # (용도 확인 필요)
├── manage.py        # Django 관리 스크립트
├── pyproject.toml   # 프로젝트 의존성 및 메타데이터
└── README.md        # 프로젝트 설명서
```

## 관리자 명령어

`stocks` 앱은 데이터 수집 및 관리를 위한 여러 관리자 명령어를 제공합니다.

*   `python manage.py import_stocks`: 주식 종목 기본 정보를 가져옵니다.
*   `python manage.py update_stock_metrics`: 주식의 주요 지표를 업데이트합니다.
*   `python manage.py update_sp500_status`: S&P 500 포함 여부를 업데이트합니다.
*   `python manage.py get_subjects`: 재무제표 계정과목을 수집합니다.
*   `python manage.py collect_financial_items`: 개별 주식의 재무 데이터를 수집합니다.
*   `python manage.py create_ai_reports`: AI 분석 리포트를 생성합니다.



sudo systemctl stop gunicorn celery_default_worker celery_pytorch_worker celery_beat

sudo systemctl start gunicorn celery_default_worker celery_pytorch_worker celery_beat