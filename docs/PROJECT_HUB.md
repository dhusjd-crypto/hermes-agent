# Hermes Automation — Kalıcı Proje Merkezi

> Bu belge, Hermes Automation’ın sohbetten, kişisel bağlamdan veya geçmiş aramasından bağımsız kalıcı proje özetidir. Vault/şifre kasası ayrı bir projedir ve bu belgede sır veya Vault durumu tutulmaz.

**Son güncelleme:** 2026-09-05

## 1. Projenin amacı

Aynı Hermes agent core’unu CLI, messaging gateway, TUI ve desktop üzerinden çalıştırmak; skill/memory, scheduled automation, delegation, remote peer ve worker akışlarını güvenli, izlenebilir ve güncellenebilir hale getirmek.

Hermes Automation’ın amacı, bir görevi alıp doğru profile/worker’a ulaştırmak, çalıştırmak, sonucu aynı run kimliğiyle geri almak ve test/CI/PR kanıtını görünür kılmaktır.

## 2. Güncel durum

- Hermes Agent; CLI, gateway, TUI ve desktop yüzeylerinde ortak agent core kullanır; platformlar ve provider’lar edge/plugin yaklaşımıyla genişler.
- Scheduled automation, delegation ve birden çok terminal backend’i ürünün temel kabiliyetleridir.
- Remote peer executor, peer recovery ve Windows Worker köprüsü için operasyonel akış ve smoke/regression kabulleri tanımlanmıştır; canlı durum her zaman ilgili issue, PR veya CI kanıtından doğrulanır.
- Profil/multiplex çalışma modeli vardır; profile secret ve authorization değerleri scope-aware ve fail-closed okunmalıdır.
- Bu repo için 100/100 iddiası yoktur. Vault’a ait kurulum puanları ve şifre kasası kabul maddeleri Hermes Automation durumuna yazılmaz.

## 3. Ana fikirler

- Per-conversation prompt cache korunur; geçmiş bağlamı gereksiz yere yeniden kurmak maliyet ve süreyi artırır.
- Core dar bir bel kemiğidir; capability çoğunlukla CLI komutu, skill, plugin veya servis-gated tool olarak kenarlarda yaşar.
- Aynı görevin yerel, remote peer, Windows worker veya başka backend’de çalışması ortak sözleşme ve kanıt formatını bozmaz.
- Otomasyon görünür olmalıdır: input, profile, run, heartbeat, retry, result, failure ve acceptance kanıtı izlenebilir olur.
- Varsayılanlar güvenli; geri dönüşü zor eylemler onay kapısından geçer.

## 4. Temel kararlar

1. Profile izolasyonu tenant/credential/authorization sınırlarını korur; secondary profile değeri default environment’tan ödünç alınmaz.
2. Hermes home yolları hardcode edilmez; profile-aware yardımcılar kullanılır.
3. Süreç kimliği argv içinde kaba substring aramasıyla tahmin edilmez; canonical matcher ve tam komut satırı kullanılır.
4. Streaming adapter’larda draft prefix-stable, final consumer tarafından authoritative ve duplicate gönderim reconcile/edit ile çözülür.
5. Testler hermetik runner üzerinden çalışır; doğrudan pytest çağrısı yerine scripts/run_tests.sh kullanılır.
6. Her değişiklik küçük, gözden geçirilebilir branch/commit/PR ile taşınır; stale branch squash merge edilmez.

## 5. Temel değişiklikler

- Hermes Kanban görevlerini remote peer/profile’a ulaştıran executor zarfı ve run kimliği koruma yaklaşımı oluşturuldu.
- Peer erişilememe/crash durumlarında blocked → ready → yeniden gönderim recovery akışı tanımlandı.
- Windows Worker gateway ve görev kuyruğu, worker çevrimdışıyken bekleme ve çevrimiçi olduğunda recovery kabulleriyle işletilir.
- Profile-scoped secret ve authorization okumaları fail-closed olacak şekilde ele alınır; bu sınır routing ve güvenlik için kritik kabul edilir.
- Acceptance, test ve CI çıktıları proje durumunun parçasıdır; kodun çalışıyor görünmesi tek başına kabul sayılmaz.

## 6. En sık problemler ve kalıcı çözümler

| Problem | Kalıcı çözüm |
|---|---|
| Secondary profile’ın default secret/allowlist değerini görmesi | Scope-aware resolver kullan; scoped miss sonrası os.environ fallback yapma. |
| Erişilebilir peer’ın offline sanılması | Yeterli probe timeout, heartbeat ve recovery regression testi. |
| Worker çalışma alanının salt okunur olması | Worker için yazılabilir çalışma alanı ve başlangıç health check’i. |
| ~/.hermes yolunun profile’ları bozması | get_hermes_home()/display_hermes_home() yardımcılarını kullan. |
| Process identity’nin flag değerinden yanlış çıkarılması | Canonical argv matcher ve tam cmdline kullan. |
| Streaming final’in iki kez gönderilmesi | Prefix-stable draft, authoritative finish ve edit-first reconciliation. |
| Testin CI’dan farklı ortamda çalışması | scripts/run_tests.sh ile hermetik test ortamını koru. |
| Eski branch’in yeni fix’i geri alması | Merge öncesi branch’i güncelle, diff’i kontrol et, sonra PR’ı birleştir. |

## 7. Fikirler ve sonraki yön

- Her remote run için tek bakışta profile, peer, lifecycle, retry, result ve acceptance kanıtı gösteren bir özet üretmek.
- Worker ve gateway health/recovery ölçümlerini otomatik PR/issue kanıtına bağlamak.
- Capability’leri core’a eklemek yerine skill/plugin/service-gated yüzeylerde standartlaştırmak.
- Upstream güncellemelerinde profile, streaming ve process-topology regression kapılarını otomatik korumak.
- Chat, worker, CLI ve gateway aynı proje merkezini okuyup yalnız gerçekleşen değişiklikleri geri yazsın.

## 8. Güncelleme kuralı

Her Hermes Automation sohbeti, worker çalışması veya Codex görevi:

1. Önce bu belgeyi ve repository development guide’ı okur.
2. Vault/şifre kasası durumunu bu belgeye taşımaz; sır değerlerini hiçbir yere yazmaz.
3. Anlamlı değişiklikten sonra durum, kanıt veya kalan tek adımı günceller.
4. Test çalışmadıysa PASS demez; host, CI veya bağlantı engelini açıkça yazar.
5. Live deployment iddiasını issue/PR/CI kanıtı olmadan yapmaz.

## 9. Kaynaklar

- [Hermes README](../README.md)
- [Hermes development guide](../AGENTS.md)
- [Project hub](PROJECT_HUB.md)
- [Hermes Agent documentation](https://hermes-agent.nousresearch.com/docs/)
