import { Link } from 'react-router-dom';

import Header from '../components/layout/Header';

const courses = [
  { region: '강원 고성', title: '해파랑길 49코스', meta: '12.3km · 약 3시간', level: '보통', color: 'blue' },
  { region: '강원 속초', title: '영랑호 둘레길', meta: '8.1km · 약 1시간 20분', level: '쉬움', color: 'green' },
  { region: '강원 양양', title: '낙산 해변 코스', meta: '16.8km · 약 3시간 40분', level: '어려움', color: 'red' },
];

export default function Home() {
  return (
    <main>
      <Header />

      <section className="hero" id="top">
        <div className="route-line route-one" />
        <div className="route-line route-two" />
        <div className="hero-copy">
          <div className="eyebrow"><span />대한민국 해안 트레일 러닝</div>
          <h1>바다를 따라,<br /><em>나답게 달려요</em></h1>
          <p>두루누비의 아름다운 해안길부터 러너들이 만든 특별한 코스까지.<br />오늘 달리고 싶은 길을 발견해보세요.</p>
          <div className="hero-buttons">
            <a className="primary-button" href="#courses">코스 둘러보기 <span>→</span></a>
            <a className="text-button" href="#how">두루런 사용법 <span>↘</span></a>
          </div>
          <div className="quick-stats" aria-label="서비스 통계">
            <div><strong>50+</strong><span>공식 해안 코스</span></div>
            <div><strong>1,284</strong><span>누적 완주 기록</span></div>
            <div><strong>4.8</strong><span>러너 만족도</span></div>
          </div>
        </div>

        <div className="hero-visual" aria-label="해안길을 달리는 두루미 캐릭터">
          <div className="sun" />
          <div className="mountain mountain-back" />
          <div className="mountain mountain-front" />
          <div className="sea"><i /><i /><i /></div>
          <img className="crane" src="/assets/durumi.png" alt="두루런 대표 캐릭터 두루미" />
          <div className="crane-message"><span>오늘도</span><strong>함께 달려요!</strong></div>
          <div className="location-pill"><span className="pin">●</span><div><small>지금 인기 있는 코스</small><strong>해파랑길 49코스</strong></div></div>
        </div>
      </section>

      <section className="discovery" id="courses">
        <div className="section-heading">
          <div><span className="section-kicker">이번 주 추천</span><h2>어떤 길을 달려볼까요?</h2></div>
          <Link to="/courses">전체 코스 보기 <span>→</span></Link>
        </div>
        <div className="course-grid">
          {courses.map((course, index) => (
            <article className={`course-card ${course.color}`} key={course.title}>
              <div className="course-art"><span className="course-number">0{index + 1}</span><div className="mini-route" /><span className="course-badge">{course.level}</span></div>
              <div className="course-info"><span>{course.region}</span><h3>{course.title}</h3><p>{course.meta}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="how" id="how">
        <div><span className="section-kicker">두루런 사용법</span><h2>길을 찾고, 달리고,<br />기록을 남겨요.</h2></div>
        <div className="steps">
          <div><b>01</b><strong>코스 발견</strong><span>내게 맞는 해안 코스를 찾아요</span></div>
          <div><b>02</b><strong>러닝 시작</strong><span>GPS로 안전하게 기록해요</span></div>
          <div><b>03</b><strong>완주 인증</strong><span>나만의 발자국을 남겨요</span></div>
        </div>
      </section>
    </main>
  );
}
