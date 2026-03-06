# locustfile.py
from locust import HttpUser, task, between

class WebsiteUser(HttpUser):
    wait_time = between(1, 5)  # 사용자가 각 작업을 하고 1~5초 정도 머무름

    @task # 사용자의 기본 작업 1
    def view_dashboard(self):
        # 대시보드 페이지에 GET 요청을 보냅니다.
        self.client.get("/dashboard/")

    @task(3) # 이 작업은 다른 작업보다 3배 더 자주 실행됩니다.
    def search_stock(self):
        # 검색 페이지에 접속하고, 특정 키워드로 검색을 시도합니다.
        self.client.get("/search/")
        # 예시: '삼성'으로 검색
        self.client.get("/api/stocks/search/?q=nvda", name="/api/search/[query]")

    def on_start(self):
        # 테스트 사용자가 생성될 때 실행되는 코드 (예: 로그인)
        pass