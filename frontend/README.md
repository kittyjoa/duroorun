# 두루런 프론트엔드 홈 시안

Vite + React로 만든 두루런 홈 화면 코드입니다.

## 포함 화면

- `/` : 반응형 웹 홈페이지
- `/app-preview` : 모바일 앱 홈 화면 시안

## 실행 방법

```bash
npm install
npm run dev
```

터미널에 표시되는 주소를 브라우저에서 열면 됩니다.

## 프로젝트에 합치는 방법

기존 프로젝트에 Vite React `frontend` 폴더가 없다면 이 폴더의 이름을
`frontend`로 변경해 프로젝트 루트에 넣으면 됩니다.

기존 `frontend`가 있다면 다음 항목을 옮겨 사용하세요.

- `src/pages/HomePage.jsx`
- `src/pages/AppPreviewPage.jsx`
- `src/styles/global.css`
- `public/assets/durumi.png`
- `public/fonts/GANGWONSTATE-SemiBold.ttf`

기존 React Router를 사용한다면 `App.jsx` 대신 다음과 같이 등록하세요.

```jsx
<Route path="/" element={<HomePage />} />
<Route path="/app-preview" element={<AppPreviewPage />} />
```

## 브랜드 색상

- 강원 그린: `#0DB14B`
- 강원 블루: `#005BAA`
- 강원 레드: `#ED174C`
- 강원 그레이: `#77787B`

현재 코스와 기록 데이터는 디자인 확인을 위한 샘플입니다. 실제 API 연결 시
각 페이지 상단의 배열을 API 응답 데이터로 교체하면 됩니다.
