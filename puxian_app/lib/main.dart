import 'package:flutter/material.dart';
import 'screens/login_screen.dart';

void main() {
  runApp(const PuxianApp());
}

class PuxianApp extends StatelessWidget {
  const PuxianApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '莆仙话训练',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF667EEA),
        useMaterial3: true,
        brightness: Brightness.light,
        appBarTheme: const AppBarTheme(
          centerTitle: true,
          elevation: 0,
        ),
      ),
      home: const LoginScreen(),
    );
  }
}
