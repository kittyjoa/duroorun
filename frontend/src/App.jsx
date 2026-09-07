import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { UserProvider } from './contexts/UserContext';
import AppPreviewPage from './pages/AppPreviewPage';
import CourseDetail from './pages/CourseDetail';
import CourseList from './pages/CourseList';
import CustomCourseForm from './pages/CustomCourseForm';
import HomePage from './pages/HomePage';
import Login from './pages/Login';
import MyCourses from './pages/MyCourses';
import MyPage from './pages/MyPage';
import OAuthCallback from './pages/OAuthCallback';
import Onboarding from './pages/Onboarding';

const App = () => {
  return (
    <BrowserRouter>
      <UserProvider>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/app-preview" element={<AppPreviewPage />} />
          <Route path="/login" element={<Login />} />
          <Route path="/oauth/callback" element={<OAuthCallback />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/mypage" element={<MyPage />} />
          <Route path="/courses" element={<CourseList />} />
          <Route path="/courses/custom/mine" element={<MyCourses />} />
          <Route path="/courses/custom/new" element={<CustomCourseForm />} />
          <Route path="/courses/custom/:courseId/edit" element={<CustomCourseForm />} />
          <Route path="/courses/:courseType/:courseId" element={<CourseDetail />} />
        </Routes>
      </UserProvider>
    </BrowserRouter>
  );
};

export default App;
