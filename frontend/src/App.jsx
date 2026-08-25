import { BrowserRouter, Route, Routes } from 'react-router-dom';

import AppPreviewPage from './pages/AppPreviewPage';
import CourseDetail from './pages/CourseDetail';
import CourseList from './pages/CourseList';
import HomePage from './pages/HomePage';
import Login from './pages/Login';
import OAuthCallback from './pages/OAuthCallback';
import Onboarding from './pages/Onboarding';

const App = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/app-preview" element={<AppPreviewPage />} />
        <Route path="/login" element={<Login />} />
        <Route path="/oauth/callback" element={<OAuthCallback />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/courses" element={<CourseList />} />
        <Route path="/courses/:courseId" element={<CourseDetail />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
