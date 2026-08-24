import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiFetch, clearAccessToken } from '../../api';
import { useUser } from '../../contexts/UserContext';

const Header = () => {
  const navigate = useNavigate();
  const profileMenuRef = useRef(null);
  const { user, setUser } = useUser();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const handleClickOutside = (event) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen]);

  const handleLogout = async () => {
    try {
      await apiFetch('/v1/auth/logout', { method: 'POST' });
    } finally {
      clearAccessToken();
      setUser(null);
      setMenuOpen(false);
      navigate('/', { replace: true });
    }
  };

  return (
    <header className="site-header">
      <a className="brand" href="/" aria-label="두루런 홈">
        <span className="brand-mark">두루</span><span>런</span>
      </a>
      <nav aria-label="주요 메뉴">
        <a href="/#courses">코스 찾기</a>
        <a href="/#records">러닝 기록</a>
        <a href="/#custom">나만의 코스</a>
      </nav>
      <div className="header-actions">
        <button className="icon-button" aria-label="검색"><span className="search-icon" /></button>
        {user ? (
          <div className="profile-menu" ref={profileMenuRef}>
            <div className="profile-avatar" aria-hidden="true">
              {user.profile_image_url ? (
                <img src={user.profile_image_url} alt="" />
              ) : (
                <span>{(user.nickname || '두').charAt(0)}</span>
              )}
            </div>
            <button
              type="button"
              className="profile-nickname"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
            >
              {user.nickname || '이름 없음'}
            </button>
            {menuOpen && (
              <div className="profile-dropdown" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate('/mypage');
                  }}
                >
                  마이페이지
                </button>
                <button type="button" role="menuitem" onClick={handleLogout}>
                  로그아웃
                </button>
              </div>
            )}
          </div>
        ) : (
          <button className="login-button" onClick={() => navigate('/login')}>로그인</button>
        )}
      </div>
    </header>
  );
};

export default Header;
