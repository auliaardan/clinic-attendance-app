# Panduan Manager — Sistem Absensi Klinik

Panduan ini menjelaskan cara menambahkan karyawan dan menjalankan fungsi utama website absensi klinik.

## 1. Masuk ke Portal Manager

1. Buka halaman utama website.
2. Pilih **Portal Manager**.
3. Masukkan username dan password manager.
4. Setelah login, manager dapat membuka:
   - **Dashboard Manager** untuk memantau absensi.
   - **Open Admin** untuk mengelola karyawan dan data dasar.
   - **Roster** untuk memeriksa dan menyetujui jadwal.
   - **Review Pengajuan** untuk memproses cuti dan koreksi absensi.

> Akun manager harus memiliki akses staff pada sistem. Jangan membagikan username atau password manager kepada karyawan.

---

## 2. Menambahkan Karyawan Baru

Penambahan karyawan terdiri dari **dua tahap**. Keduanya harus dilakukan agar karyawan dapat memakai sistem dan muncul di roster.

### Tahap A — Membuat data Employee

1. Dari **Dashboard Manager**, pilih **Open Admin**.
2. Buka menu **Employees**.
3. Pilih **Add Employee**.
4. Isi:
   - **Name**: nama lengkap karyawan.
   - **Is active**: harus dicentang agar karyawan dapat melakukan absensi dan login Portal Staff.
   - **PIN**: buat PIN unik yang terdiri dari tepat **6 angka**.
5. Pilih **Save**.

Sampaikan PIN hanya kepada karyawan yang bersangkutan. Jangan mencantumkan PIN di grup umum.

### Tahap B — Menghubungkan karyawan ke divisi

1. Kembali ke halaman Admin.
2. Buka menu **Employee Profiles**.
3. Pilih **Add Employee Profile**.
4. Isi:
   - **Employee**: pilih karyawan yang baru dibuat.
   - **Division**: pilih divisi/unit kerja karyawan.
   - **Is rostered**: centang agar karyawan muncul dalam roster mingguan.
5. Pilih **Save**.

### Pemeriksaan setelah menambahkan karyawan

Pastikan:

- Nama karyawan muncul pada halaman **Mulai Absensi**.
- Karyawan dapat masuk ke **Portal Staff** menggunakan nama dan PIN.
- Nama karyawan muncul pada roster divisinya.

Jika nama muncul pada absensi tetapi tidak muncul pada roster, periksa **Employee Profile**, **Division**, dan pilihan **Is rostered**.

---

## 3. Mengubah PIN atau Menonaktifkan Karyawan

### Mengganti PIN

1. Buka **Open Admin** → **Employees**.
2. Pilih nama karyawan.
3. Isi PIN baru dengan tepat 6 angka.
4. Pilih **Save**.

PIN lama tetap digunakan apabila kolom PIN dibiarkan kosong.

### Karyawan berhenti atau tidak lagi aktif

1. Buka data karyawan pada **Employees**.
2. Hilangkan centang **Is active**.
3. Pilih **Save**.

Sebaiknya nonaktifkan karyawan daripada menghapusnya agar riwayat absensi tetap tersimpan.

---

## 4. Data Dasar yang Diperlukan untuk Roster

Data berikut biasanya hanya disiapkan sekali atau saat ada perubahan:

### Division

Menu **Divisions** digunakan untuk membuat unit kerja, misalnya Dokter, Perawat, Farmasi, Administrasi, atau Laboratorium. Pastikan **Is active** dicentang.

### Shift Template

Menu **Shift Templates** digunakan untuk membuat pilihan jam kerja per divisi, misalnya:

- Pagi: 08.00–14.00
- Siang: 14.00–20.00
- Malam: 20.00–08.00

Isi divisi, nama shift, jam mulai, jam selesai, dan aktifkan template.

### Division Roster Editor

Menu ini digunakan untuk memberikan akses kepada kepala divisi atau petugas tertentu agar dapat mengisi roster divisinya. Manager tetap bertugas memeriksa dan menyetujui roster yang telah dikirim.

---

## 5. Mengelola Roster Mingguan

1. Buka **Roster**.
2. Pilih **Division**.
3. Pilih tanggal **Week starting (Monday)**.
4. Periksa jadwal setiap karyawan untuk tujuh hari tersebut.
5. Jika roster telah dikirim dan belum disetujui, pilih **Approve week**.

Status roster:

- **SUBMITTED**: roster telah dikirim dan menunggu persetujuan manager.
- **APPROVED**: roster telah disetujui dan digunakan untuk menghitung tepat waktu, terlambat, dan tidak hadir.

> Statistik kehadiran dapat kosong atau tidak akurat apabila roster belum berstatus APPROVED.

Pada tampilan manager, roster bersifat pemeriksaan/persetujuan. Pengisian roster dilakukan oleh pengguna yang diberi akses sebagai editor divisi.

---

## 6. Menggunakan Dashboard Manager

Dashboard Manager dapat difilter berdasarkan:

- **Date**: tanggal yang ingin diperiksa.
- **Division**: seluruh divisi atau satu divisi tertentu.

### Ringkasan utama

- **Scheduled shifts**: jumlah shift yang sudah disetujui.
- **Attended shifts**: shift yang memiliki absensi yang sesuai.
- **On-time**: hadir dalam batas toleransi.
- **Late**: hadir melewati batas toleransi.
- **No-show**: tidak ada absensi yang memenuhi setelah batas waktu.
- **Currently open**: karyawan yang masih berstatus clock-in.
- **Missing clock-outs**: karyawan yang belum clock-out melewati toleransi.
- **Proxy events**: absensi yang dilakukan dengan bantuan saksi.
- **Locked PIN attempts**: PIN yang terkunci sementara karena beberapa kali salah.

### Exception Inbox

Bagian ini menampilkan kejadian yang perlu diperiksa, seperti:

- terlambat;
- tidak hadir;
- belum clock-out;
- sesi terlalu lama terbuka;
- absensi tanpa roster yang disetujui;
- absensi proxy;
- PIN terkunci.

### Latest events dan foto

Bagian **Latest events** menampilkan waktu, jenis kejadian IN/OUT, nama karyawan, saksi, status proxy, dan foto bukti. Foto hanya boleh digunakan untuk verifikasi absensi dan harus dijaga kerahasiaannya.

### Export laporan

1. Pilih tanggal dan divisi pada dashboard.
2. Pilih **Apply**.
3. Pilih **Export CSV**.
4. File dapat dibuka dengan Microsoft Excel atau aplikasi spreadsheet lainnya.

---

## 7. Review Cuti dan Koreksi Absensi

1. Buka **Review Pengajuan**.
2. Pilih status pengajuan yang ingin dilihat.
3. Periksa nama karyawan, tanggal, alasan, dan data absensi terkait.
4. Pilih **Approve** atau **Reject**.
5. Untuk koreksi absensi, tambahkan catatan manager bila diperlukan.

Catatan penting: persetujuan koreksi saat ini mencatat keputusan manager, tetapi tidak otomatis mengubah waktu pada sesi absensi asli. Perubahan data absensi harus diverifikasi sesuai prosedur administrasi yang berlaku.

Cuti yang berstatus **APPROVED** tidak dihitung sebagai no-show pada tanggal cuti tersebut.

---

## 8. Alur Absensi Karyawan

### Absensi harian

1. Karyawan membuka **Mulai Absensi** menggunakan perangkat yang berada di lokasi klinik.
2. Scan QR yang ditampilkan pada layar klinik.
3. Pilih nama karyawan.
4. Ambil foto selfie langsung.
5. Masukkan PIN 6 angka.
6. Sistem menentukan tindakan berikutnya sebagai **IN** atau **OUT**.
7. Kirim absensi dan pastikan muncul pesan berhasil.

QR berganti secara berkala dan foto wajib diambil saat absensi.

### Proxy atau bantuan saksi

Jika karyawan tidak memiliki perangkat, karyawan lain dapat membantu sebagai saksi. Sistem meminta:

- PIN karyawan yang melakukan absensi;
- PIN saksi;
- foto karyawan yang bersangkutan.

Karyawan tidak boleh menjadi saksi untuk dirinya sendiri.

### Portal Staff

Melalui **Portal Staff**, karyawan dapat:

- melihat status IN/OUT;
- melihat roster yang telah disetujui;
- melihat riwayat absensi;
- mengajukan cuti;
- mengajukan koreksi absensi;
- melihat status pengajuan.

Sesi login Portal Staff berakhir otomatis setelah tidak digunakan dalam jangka waktu tertentu.

---

## 9. Masalah yang Sering Terjadi

### Karyawan tidak muncul pada halaman absensi

Periksa apakah **Is active** pada data Employee sudah dicentang.

### Karyawan tidak muncul pada roster

Periksa apakah sudah dibuat **Employee Profile**, divisi sudah dipilih, dan **Is rostered** sudah dicentang.

### Statistik menunjukkan tidak ada roster

Pastikan roster minggu tersebut sudah disetujui dan berstatus **APPROVED**.

### PIN salah atau terkunci

Setelah beberapa kali percobaan PIN yang salah, akses dapat terkunci sementara. Tunggu masa penguncian selesai atau pastikan PIN yang digunakan benar. Jika lupa, manager dapat mengganti PIN melalui Admin.

### Karyawan sudah IN tetapi tidak bisa IN lagi

Karyawan harus melakukan **OUT** terlebih dahulu. Satu karyawan hanya dapat memiliki satu sesi terbuka.

### Foto tidak dapat dibuka

Pastikan file foto masih tersimpan pada server. Data kejadian absensi dapat tetap ada meskipun file foto lama telah dibersihkan sesuai kebijakan penyimpanan.

---

## 10. Pemeriksaan Rutin Manager

### Setiap hari

- Periksa **Exception Inbox**.
- Periksa siapa yang masih berstatus **IN**.
- Tindak lanjuti no-show, keterlambatan, missing clock-out, dan proxy event.
- Review pengajuan baru.

### Setiap minggu

- Pastikan roster seluruh divisi sudah dikirim.
- Periksa jadwal sebelum menyetujui.
- Pilih **Approve week** agar statistik dapat dihitung.

### Setiap bulan

- Export laporan CSV sesuai kebutuhan.
- Periksa karyawan aktif dan nonaktif.
- Pastikan pembagian divisi dan template shift masih sesuai.
- Batasi akses manager dan roster editor hanya kepada pengguna yang berwenang.
