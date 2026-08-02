import AppPreviewPage from './pages/AppPreviewPage';
import HomePage from './pages/HomePage';

const App = () => {
  // 미리보기 주소를 유지하면서 별도 라우터 의존성 없이 두 화면을 확인합니다.
  const isAppPreview = window.location.pathname.startsWith('/app-preview');

  return isAppPreview ? <AppPreviewPage /> : <HomePage />;
};

export default App;
