// 카카오맵 JS SDK를 지도가 실제로 필요한 시점에만 동적으로 로드.
// (index.html에 고정 <script>로 넣으면 지도가 없는 페이지에서도 항상 로드됨)
let loadPromise = null;

export const loadKakaoMaps = () => {
  if (window.kakao?.maps) {
    return Promise.resolve(window.kakao);
  }
  if (loadPromise) return loadPromise;

  // loadPromise: 지금 로드중인/이미끝난 Promise 캐싱
  loadPromise = new Promise((resolve, reject) => {
    const appKey = import.meta.env.VITE_KAKAO_JS_KEY;
    if (!appKey) {
      loadPromise = null; // 실패하면 다음 시도 때 다시 로드하도록 캐시 X
      reject(new Error('VITE_KAKAO_JS_KEY가 설정되지 않았습니다.'));
      return;
    }

    const script = document.createElement('script');
    // autoload=false + kakao.maps.load(cb): false로 자동 초기화 끄고
    // 스크립트가 다운로드 완료된뒤(script.onload) 직접 부름 (타이밍 통제)
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appKey}&autoload=false&libraries=services`;
    script.async = true;
    script.onerror = () => {
      loadPromise = null; // 실패하면 다음 시도 때 다시 로드하도록 캐시 X
      reject(new Error('카카오맵 SDK를 불러오지 못했습니다.'));
    };
    script.onload = () => {
      // 스크립트 다운로드는 됐지만 SDK 객체가 없는 비정상 상황 방어
      if (!window.kakao?.maps) {
        loadPromise = null;
        reject(new Error('카카오맵 SDK를 불러오지 못했습니다.'));
        return;
      }
      window.kakao.maps.load(() => resolve(window.kakao));
    };
    document.head.appendChild(script);
  });

  return loadPromise;
};
