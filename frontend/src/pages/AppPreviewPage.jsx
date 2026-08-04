const appCourses = [
  { place: '고성 · 화진포', name: '해파랑길 49코스', distance: '12.3km', tone: 'blue' },
  { place: '속초 · 영랑호', name: '영랑호 둘레길', distance: '8.1km', tone: 'green' },
];

export default function AppPreview() {
  return (
    <main className="app-preview-page">
      <section className="phone-app" aria-label="두루런 모바일 앱 홈 화면">
        <div className="app-status"><span>9:41</span><span className="status-icons">● ◒ ▰</span></div>

        <header className="app-header">
          <a className="app-brand" href="/">두루<span>런</span></a>
          <div className="app-header-actions">
            <button aria-label="알림"><span className="bell">♢</span><i /></button>
            <button className="profile-dot" aria-label="마이페이지">도</button>
          </div>
        </header>

        <div className="app-scroll">
          <section className="app-welcome">
            <p>도희님, 오늘도 반가워요!</p>
            <h1>오늘은 어디로<br /><em>달려볼까요?</em></h1>
            <img src="/assets/durumi.png" alt="달릴 준비를 하는 두루미" />
            <span className="speech">날씨가 좋아요!</span>
          </section>

          <button className="location-search"><span className="location-mark">●</span><span><small>현재 위치</small><strong>내 주변 코스 찾아보기</strong></span><b>›</b></button>

          <section className="run-card">
            <div className="run-map">
              <span className="map-road road-a" /><span className="map-road road-b" /><span className="map-road road-c" />
              <span className="route-track" /><span className="current-pin">●</span>
            </div>
            <div className="run-content">
              <span><small>바로 달리기</small><strong>GPS 러닝 기록</strong></span>
              <button>러닝 시작 <b>▶</b></button>
            </div>
          </section>

          <section className="weekly">
            <div className="app-section-title"><div><small>나의 이번 주</small><h2>러닝 기록</h2></div><a href="#record">전체보기</a></div>
            <div className="record-panel">
              <div className="record-main"><span>이번 주 거리</span><strong>18.7<small> km</small></strong><em>지난주보다 3.2km 더 달렸어요</em></div>
              <div className="mini-bars" aria-label="요일별 러닝 거리 막대 그래프">
                {[22,44,18,64,30,78,38].map((height,index)=><span key={index}><i style={{height:`${height}%`}} /><small>{['월','화','수','목','금','토','일'][index]}</small></span>)}
              </div>
            </div>
          </section>

          <section className="app-recommend">
            <div className="app-section-title"><div><small>두루미의 추천</small><h2>바다 옆 달리기 좋은 길</h2></div><a href="#courses">더보기</a></div>
            <div className="app-course-list">
              {appCourses.map((course,index)=><article className={`app-course ${course.tone}`} key={course.name}>
                <div className="course-thumb"><span>0{index+1}</span><i /></div>
                <div><small>{course.place}</small><h3>{course.name}</h3><p>{course.distance} · 공식 코스</p></div>
                <button aria-label={`${course.name} 저장`}>♡</button>
              </article>)}
            </div>
          </section>
        </div>

        <nav className="bottom-nav" aria-label="앱 하단 메뉴">
          <a className="active" href="#home"><i>⌂</i><span>홈</span></a>
          <a href="#course"><i>⌕</i><span>코스</span></a>
          <a className="run-fab" href="#run"><i>▶</i><span>러닝</span></a>
          <a href="#record"><i>◷</i><span>기록</span></a>
          <a href="#my"><i>♙</i><span>마이</span></a>
        </nav>
      </section>
      <aside className="preview-caption"><span>DUROORUN APP</span><h2>두루런을<br />손안에서도.</h2><p>코스를 발견하고 바로 달리는<br />모바일 앱 홈 화면 시안입니다.</p><a href="/">웹 홈 시안 보기 →</a></aside>
    </main>
  );
}
