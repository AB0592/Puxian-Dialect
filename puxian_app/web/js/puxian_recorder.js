// 浏览器原生录音 — 用 Web Audio API 抓取 PCM 原始音频，不依赖 MediaRecorder
window.PuxianRecorder = (function() {
  var audioContext = null;
  var mediaStream = null;
  var sourceNode = null;
  var scriptNode = null;
  var samples = [];
  var _stopResolve = null;
  
  return {
    start: function(maxDurationSec) {
      return new Promise(function(resolve, reject) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          reject(new Error('浏览器不支持麦克风'));
          return;
        }
        
        samples = [];
        _stopResolve = null;
        window.__puxian_audio_bytes = null;
        
        navigator.mediaDevices.getUserMedia({ audio: true })
          .then(function(stream) {
            mediaStream = stream;
            
            try {
              audioContext = new (window.AudioContext || window.webkitAudioContext)();
            } catch(e) {
              reject(new Error('AudioContext 创建失败: ' + e.message));
              return;
            }
            
            sourceNode = audioContext.createMediaStreamSource(stream);
            
            // ScriptProcessorNode — 虽然 deprecated 但兼容性最好
            scriptNode = audioContext.createScriptProcessor(4096, 1, 1);
            
            scriptNode.onaudioprocess = function(event) {
              var input = event.inputBuffer.getChannelData(0);
              for (var i = 0; i < input.length; i++) {
                samples.push(input[i]);
              }
            };
            
            sourceNode.connect(scriptNode);
            // 不连 destination！避免啸叫
            
            // AudioContext 默认 suspended，需 resume 才能触发 audioprocess
            if (audioContext.state === 'suspended') {
              audioContext.resume().then(function() {
                resolve('recording');
              }).catch(function(e) {
                reject(new Error('AudioContext 启动失败: ' + e.message));
              });
            } else {
              resolve('recording');
            }
            
            // 自动停止
            if (maxDurationSec > 0) {
              setTimeout(function() {
                if (audioContext) {
                  PuxianRecorder.stop();
                }
              }, maxDurationSec * 1000);
            }
          })
          .catch(function(err) {
            reject(new Error('无法访问麦克风: ' + err.message));
          });
      });
    },
    
    stop: function() {
      return new Promise(function(resolve) {
        if (!audioContext || samples.length === 0) {
          PuxianRecorder._cleanup();
          resolve('empty');
          return;
        }
        
        _stopResolve = resolve;
        
        // 断开节点
        if (sourceNode && scriptNode) {
          sourceNode.disconnect();
          scriptNode.disconnect();
        }
        
        // 关闭 AudioContext
        if (audioContext) {
          audioContext.close().then(function() {
            // 释放麦克风
            if (mediaStream) {
              mediaStream.getTracks().forEach(function(t) { t.stop(); });
              mediaStream = null;
            }
            
            // 把 Float32 PCM 转成 WAV
            var wav = PuxianRecorder._encodeWav(samples);
            
            // 存到全局变量给 Flutter 取
            window.__puxian_audio_bytes = new Uint8Array(wav);
            
            if (_stopResolve) {
              _stopResolve('done');
              _stopResolve = null;
            }
            
            audioContext = null;
            sourceNode = null;
            scriptNode = null;
            samples = [];
          });
        }
      });
    },
    
    _cleanup: function() {
      if (sourceNode && scriptNode) {
        sourceNode.disconnect();
        scriptNode.disconnect();
      }
      if (audioContext) {
        audioContext.close();
      }
      if (mediaStream) {
        mediaStream.getTracks().forEach(function(t) { t.stop(); });
      }
      audioContext = null;
      sourceNode = null;
      scriptNode = null;
      mediaStream = null;
    },
    
    // Float32 PCM → WAV ArrayBuffer
    _encodeWav: function(samples) {
      var numChannels = 1;
      var sampleRate = 48000; // AudioContext 默认 48kHz
      var bitsPerSample = 16;
      var numSamples = samples.length;
      var byteRate = sampleRate * numChannels * bitsPerSample / 8;
      var blockAlign = numChannels * bitsPerSample / 8;
      var dataSize = numSamples * numChannels * bitsPerSample / 8;
      var bufferSize = 44 + dataSize;
      
      var buffer = new ArrayBuffer(bufferSize);
      var view = new DataView(buffer);
      
      // WAV header
      PuxianRecorder._writeString(view, 0, 'RIFF');
      view.setUint32(4, bufferSize - 8, true);
      PuxianRecorder._writeString(view, 8, 'WAVE');
      PuxianRecorder._writeString(view, 12, 'fmt ');
      view.setUint32(16, 16, true); // chunk size
      view.setUint16(20, 1, true);  // PCM format
      view.setUint16(22, numChannels, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, byteRate, true);
      view.setUint16(32, blockAlign, true);
      view.setUint16(34, bitsPerSample, true);
      PuxianRecorder._writeString(view, 36, 'data');
      view.setUint32(40, dataSize, true);
      
      // PCM data (float → int16)
      var offset = 44;
      for (var i = 0; i < numSamples; i++) {
        var s = Math.max(-1, Math.min(1, samples[i]));
        // Clamp to int16 range
        var val = s < 0 ? s * 0x8000 : s * 0x7FFF;
        view.setInt16(offset, val, true);
        offset += 2;
      }
      
      return buffer;
    },
    
    _writeString: function(view, offset, string) {
      for (var i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    },
    
    getBytes: function() {
      var bytes = window.__puxian_audio_bytes;
      if (bytes && bytes.length > 0) {
        return Array.from(bytes);
      }
      return [];
    },
    
    isRecording: function() {
      return audioContext !== null && audioContext.state !== 'closed';
    }
  };
})();
