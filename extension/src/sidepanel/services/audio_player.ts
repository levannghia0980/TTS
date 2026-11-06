export interface PlayableItem {
  id: string;
  xid: string;
  text: string;
  origAudioBlobUrl?: string;
  viAudioBlobUrl?: string;
  audioBlobUrl?: string; // backward compatibility
  failed?: boolean;
}

/**
 * Trình phát âm thanh Dual-Audio Node với Dual-Cache tách biệt tuyệt đối (Gốc vs Dịch VI):
 * 1. Tách riêng `origAudioBlobUrl` và `viAudioBlobUrl` cho từng câu -> Không bao giờ lẫn âm thanh 2 trạng thái,
 *    đồng thời tái sử dụng 100% âm thanh đã tải khi bấm chuyển qua lại giữa Gốc <-> Dịch mà không cần tải lại!
 * 2. Cơ chế `generationId` (Khóa thế hệ): Hủy bỏ hoàn toàn mọi request tải ngầm (preloadNext) của trạng thái cũ
 *    đang bay lơ lửng trên mạng khi người dùng bấm chuyển trạng thái.
 * 3. Sử dụng 2 thẻ Audio A & B luân phiên (0ms Gapless): Trong khi A đang phát, B đã nạp sẵn câu tiếp theo của đúng chế độ đó.
 */
export class AudioQueuePlayer {
  private audioA = new Audio();
  private audioB = new Audio();
  private activeSlot: 'A' | 'B' = 'A';

  private queue: PlayableItem[] = [];
  private idx = 0;
  private playing = false;
  private speed = 1.0;
  private mode: 'orig' | 'vi' = 'orig';
  private generationId = 0;
  private waitTimer: any = null;

  public onTrackChange?: (index: number, item: PlayableItem) => void;
  public onStateChange?: (isPlaying: boolean) => void;
  public onFinish?: () => void;
  public audioLoader?: (index: number, mode: 'orig' | 'vi') => Promise<string>;

  private retryCount = 0;

  constructor() {
    this.audioA.onended = () => this.handleTrackEnded();
    this.audioB.onended = () => this.handleTrackEnded();

    this.audioA.onerror = () => this.handleAudioError('A');
    this.audioB.onerror = () => this.handleAudioError('B');
  }

  private clearWaitTimer() {
    if (this.waitTimer) {
      clearInterval(this.waitTimer);
      this.waitTimer = null;
    }
  }

  private getItemAudioForMode(item: PlayableItem | undefined, targetMode: 'orig' | 'vi'): string | undefined {
    if (!item) return undefined;
    return targetMode === 'vi' ? item.viAudioBlobUrl : item.origAudioBlobUrl;
  }

  private setItemAudioForMode(item: PlayableItem | undefined, targetMode: 'orig' | 'vi', uri: string | undefined) {
    if (!item) return;
    if (targetMode === 'vi') {
      item.viAudioBlobUrl = uri;
    } else {
      item.origAudioBlobUrl = uri;
    }
  }

  public getMode(): 'orig' | 'vi' {
    return this.mode;
  }

  private handleAudioError(slot: 'A' | 'B') {
    if (slot === this.activeSlot && this.playing) {
      const gen = this.generationId;
      if (this.retryCount < 2) {
        this.retryCount++;
        console.warn(`[AudioPlayer] Đang đợi audio (${this.mode}) câu ${this.idx + 1} (thử lại lần ${this.retryCount})...`);
        setTimeout(() => {
          if (this.playing && this.generationId === gen) {
            this.playCurrent();
          }
        }, 1000);
      } else {
        this.retryCount = 0;
        console.warn(`[AudioPlayer] Câu ${this.idx + 1} (${this.mode}) chưa tải được sau 2 lần, tạm dừng đợi tạo audio`);
        this.pause();
      }
    }
  }

  private handleTrackEnded() {
    if (this.idx < this.queue.length - 1) {
      this.idx++;
      this.playSlotSwitch();
    } else {
      this.setPlaying(false);
      this.onFinish?.();
    }
  }

  setQueue(items: PlayableItem[], startIndex: number = 0, initialMode: 'orig' | 'vi' = 'orig') {
    this.generationId++;
    this.clearWaitTimer();
    this.mode = initialMode;
    this.queue = items;
    this.idx = Math.max(0, Math.min(startIndex, items.length - 1));
    this.preloadNext(this.generationId, this.mode);
  }

  updateItemAudio(id: string, audioBlobUrl: string, targetMode: 'orig' | 'vi' = this.mode) {
    const item = this.queue.find((q) => q.id === id);
    if (item) {
      this.setItemAudioForMode(item, targetMode, audioBlobUrl);

      if (targetMode !== this.mode) return;

      // Nếu là câu hiện tại đang chờ audio để phát
      const current = this.queue[this.idx];
      if (current?.id === id && this.playing) {
        const activeAudio = this.activeSlot === 'A' ? this.audioA : this.audioB;
        if (!activeAudio.src || activeAudio.paused) {
          this.playCurrent();
        }
      }

      // Nếu là câu kế tiếp: nạp ngầm vào slot dự phòng
      if (this.queue[this.idx + 1]?.id === id) {
        this.preloadNext(this.generationId, this.mode);
      }
    }
  }

  play() {
    if (!this.queue.length) return;
    this.setPlaying(true);
    this.playCurrent();
  }

  pause() {
    this.clearWaitTimer();
    this.setPlaying(false);
    this.audioA.pause();
    this.audioB.pause();
  }

  resume() {
    if (!this.queue.length) return;
    this.setPlaying(true);
    const activeAudio = this.activeSlot === 'A' ? this.audioA : this.audioB;
    if (activeAudio.src && activeAudio.currentTime > 0 && !activeAudio.ended) {
      activeAudio.play().catch(() => this.playCurrent());
    } else {
      this.playCurrent();
    }
  }

  next() {
    this.retryCount = 0;
    this.clearWaitTimer();
    if (this.idx < this.queue.length - 1) {
      this.idx++;
      this.setPlaying(true);
      this.playSlotSwitch();
    } else {
      this.pause();
      this.onFinish?.();
    }
  }

  prev() {
    this.retryCount = 0;
    this.clearWaitTimer();
    if (this.idx > 0) {
      this.idx--;
      this.setPlaying(true);
      this.playCurrent();
    }
  }

  seek(i: number) {
    this.retryCount = 0;
    this.generationId++;
    this.clearWaitTimer();
    if (i < 0 || i >= this.queue.length) return;
    this.idx = i;
    this.setPlaying(true);
    this.playCurrent();
  }

  setSpeed(s: number) {
    this.speed = s;
    this.audioA.playbackRate = s;
    this.audioB.playbackRate = s;
  }

  getCurrentIndex(): number {
    return this.idx;
  }

  private setPlaying(v: boolean) {
    if (this.playing !== v) {
      this.playing = v;
      this.onStateChange?.(v);
    }
  }

  /**
   * Phát câu hiện tại (khi seek, khởi đầu hoặc vừa đổi chế độ)
   */
  private async playCurrent() {
    const gen = this.generationId;
    const reqMode = this.mode;
    const reqIdx = this.idx;
    const item = this.queue[reqIdx];
    if (!item) return;

    this.onTrackChange?.(reqIdx, item);

    let src = this.getItemAudioForMode(item, reqMode);
    if (!src && this.audioLoader) {
      try {
        const loadedUri = await this.audioLoader(reqIdx, reqMode);
        if (loadedUri) {
          // Luôn lưu vào đúng ngăn cache của reqMode (kể cả khi người dùng đã chuyển chế độ)
          this.setItemAudioForMode(item, reqMode, loadedUri);
          src = loadedUri;
        }
      } catch (e) {
        console.warn(`[AudioPlayer] Lỗi nạp audio (${reqMode}) câu ${reqIdx}:`, e);
      }
    }

    // Nếu trong lúc chờ tải mà người dùng đã bấm chuyển chế độ hoặc nhảy câu khác -> hủy phát!
    if (this.generationId !== gen || this.mode !== reqMode || this.idx !== reqIdx) {
      return;
    }

    if (!src) {
      this.audioA.pause();
      this.audioB.pause();
      return;
    }

    const activeAudio = this.activeSlot === 'A' ? this.audioA : this.audioB;
    const standbyAudio = this.activeSlot === 'A' ? this.audioB : this.audioA;
    standbyAudio.pause();
    standbyAudio.removeAttribute('src');

    activeAudio.src = src;
    activeAudio.playbackRate = this.speed;
    if (this.playing) {
      activeAudio.play().catch((e) => console.warn('[AudioPlayer] playCurrent lỗi:', e));
    }

    this.preloadNext(gen, reqMode);
  }

  private async playSlotSwitch() {
    const gen = this.generationId;
    const reqMode = this.mode;
    const reqIdx = this.idx;
    const item = this.queue[reqIdx];
    if (!item) return;

    this.onTrackChange?.(reqIdx, item);

    // Đổi slot
    this.activeSlot = this.activeSlot === 'A' ? 'B' : 'A';
    const currentAudio = this.activeSlot === 'A' ? this.audioA : this.audioB;
    const prevAudio = this.activeSlot === 'A' ? this.audioB : this.audioA;
    prevAudio.pause();

    let src = this.getItemAudioForMode(item, reqMode);
    if (!src && this.audioLoader) {
      try {
        const loadedUri = await this.audioLoader(reqIdx, reqMode);
        if (loadedUri) {
          this.setItemAudioForMode(item, reqMode, loadedUri);
          src = loadedUri;
        }
      } catch {}
    }

    if (this.generationId !== gen || this.mode !== reqMode || this.idx !== reqIdx) {
      return;
    }

    if (!src) {
      // Nếu audio câu tiếp chưa kịp về: đợi tối đa 3.2 giây, kiểm tra mỗi 400ms thay vì ngắt tiếng
      console.warn(`[AudioPlayer] Đang đợi audio (${reqMode}) câu ${reqIdx + 1} hoàn tất...`);
      this.clearWaitTimer();
      let retryAttempts = 0;
      this.waitTimer = setInterval(async () => {
        retryAttempts++;
        if (!this.playing || this.generationId !== gen || this.mode !== reqMode || retryAttempts > 8) {
          this.clearWaitTimer();
          if (!this.getItemAudioForMode(this.queue[reqIdx], reqMode)) {
            currentAudio.pause();
          }
          return;
        }

        try {
          const retrySrc = await this.audioLoader?.(reqIdx, reqMode);
          if (retrySrc) {
            this.setItemAudioForMode(item, reqMode, retrySrc);
            if (this.generationId === gen && this.mode === reqMode && this.idx === reqIdx && this.playing) {
              this.clearWaitTimer();
              currentAudio.src = retrySrc;
              currentAudio.playbackRate = this.speed;
              currentAudio.play().catch(console.warn);
              this.preloadNext(gen, reqMode);
            }
          }
        } catch {}
      }, 400);
      return;
    }

    if (currentAudio.src === src) {
      currentAudio.playbackRate = this.speed;
      currentAudio.play().catch(() => {
        currentAudio.src = src!;
        currentAudio.playbackRate = this.speed;
        currentAudio.play().catch(console.warn);
      });
    } else {
      currentAudio.src = src;
      currentAudio.playbackRate = this.speed;
      currentAudio.play().catch(console.warn);
    }

    this.preloadNext(gen, reqMode);
  }

  private async preloadNext(gen: number = this.generationId, reqMode: 'orig' | 'vi' = this.mode) {
    if (this.generationId !== gen || this.mode !== reqMode) return;

    // 1. Nạp trước vào slot chờ (A hoặc B) cho câu kế tiếp (idx + 1) của đúng chế độ reqMode
    const nextIdx = this.idx + 1;
    const nextItem = this.queue[nextIdx];
    if (nextItem) {
      let src = this.getItemAudioForMode(nextItem, reqMode);
      if (!src && this.audioLoader) {
        try {
          const loadedUri = await this.audioLoader(nextIdx, reqMode);
          if (loadedUri) {
            this.setItemAudioForMode(nextItem, reqMode, loadedUri);
            src = loadedUri;
          }
        } catch {}
      }

      // Kiểm tra lại khóa thế hệ: Chỉ nạp vào standbyAudio nếu chế độ và vị trí chưa bị đổi!
      if (src && this.generationId === gen && this.mode === reqMode && this.idx + 1 === nextIdx) {
        const standbyAudio = this.activeSlot === 'A' ? this.audioB : this.audioA;
        if (standbyAudio.src !== src) {
          standbyAudio.src = src;
          standbyAudio.playbackRate = this.speed;
          standbyAudio.load();
        }
      }
    }

    // 2. Pre-fetch thêm 3 câu tiếp theo (idx + 2, idx + 3, idx + 4) vào đúng ngăn cache của reqMode
    for (let ahead = 2; ahead <= 4; ahead++) {
      const aheadIdx = this.idx + ahead;
      const aheadItem = this.queue[aheadIdx];
      if (aheadItem && !this.getItemAudioForMode(aheadItem, reqMode) && this.audioLoader) {
        this.audioLoader(aheadIdx, reqMode).then((uri) => {
          if (uri && aheadItem) {
            // Lưu đúng vào ngăn origAudioBlobUrl hoặc viAudioBlobUrl của reqMode
            this.setItemAudioForMode(aheadItem, reqMode, uri);
          }
        }).catch(() => {});
      }
    }
  }

  /**
   * Dừng và làm sạch 2 khe phát vật lý (A & B), tăng generationId để chặn mọi tác vụ ngầm cũ.
   */
  private stopAndFlushAudioSlots() {
    this.generationId++;
    this.clearWaitTimer();
    this.audioA.pause();
    this.audioB.pause();
    this.audioA.removeAttribute('src');
    this.audioB.removeAttribute('src');
    this.audioA.load();
    this.audioB.load();
    this.activeSlot = 'A';
  }

  /**
   * Chuyển đổi mượt mà giữa trạng thái Bản Gốc ('orig') và Bản Dịch ('vi'):
   * - Giữ nguyên 100% cache `origAudioBlobUrl` và `viAudioBlobUrl` đã tải trước đó để dùng lại ngay lập tức!
   * - Xóa sạch tàn dư trên 2 khe phát `audioA`/`audioB` và hủy mọi request đang bay của chế độ cũ.
   * - Đưa con trỏ đọc về câu đầu tiên (index 0) của trạng thái mới.
   */
  switchModeAndResetToStart(newMode: 'orig' | 'vi', autoPlay: boolean = false) {
    this.mode = newMode;
    this.stopAndFlushAudioSlots();
    this.idx = 0;
    this.retryCount = 0;

    if (autoPlay && this.queue.length > 0) {
      this.setPlaying(true);
      this.playCurrent();
    } else {
      this.setPlaying(false);
      // Vẫn nạp trước ngầm câu 0, 1, 2 của chế độ mới để bấm Play là kêu ngay
      this.preloadFromStart(this.generationId, newMode);
    }
  }

  private async preloadFromStart(gen: number, reqMode: 'orig' | 'vi') {
    for (let i = 0; i < Math.min(3, this.queue.length); i++) {
      if (this.generationId !== gen || this.mode !== reqMode) return;
      const item = this.queue[i];
      if (item && !this.getItemAudioForMode(item, reqMode) && this.audioLoader) {
        this.audioLoader(i, reqMode).then((uri) => {
          if (uri && item) {
            this.setItemAudioForMode(item, reqMode, uri);
          }
        }).catch(() => {});
      }
    }
  }

  /**
   * Xóa sạch toàn bộ cache âm thanh (dùng khi người dùng đổi giọng đọc khác trong Settings)
   */
  clearCache(onlyVi: boolean = false) {
    this.stopAndFlushAudioSlots();
    this.queue.forEach((q) => {
      q.viAudioBlobUrl = undefined;
      q.audioBlobUrl = undefined;
      if (!onlyVi) {
        q.origAudioBlobUrl = undefined;
      }
    });
  }

  /**
   * Reset con trỏ về câu số 1 (index 0) khi đổi giọng đọc mới
   */
  resetToStart(autoPlay: boolean = false, clearAllAudio: boolean = true) {
    if (clearAllAudio) {
      this.clearCache(false);
    } else {
      this.stopAndFlushAudioSlots();
    }
    this.idx = 0;
    this.retryCount = 0;
    if (autoPlay && this.queue.length > 0) {
      this.setPlaying(true);
      this.playCurrent();
    } else {
      this.setPlaying(false);
    }
  }

  /**
   * Dọn sạch hoàn toàn khi tắt trang
   */
  reset() {
    this.stopAndFlushAudioSlots();
    this.queue = [];
    this.idx = 0;
    this.playing = false;
    this.onStateChange?.(false);
  }
}
