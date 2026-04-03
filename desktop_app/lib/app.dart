import 'package:flutter/material.dart';

import 'screens/provisioning_wizard_screen.dart';

class InkyCalApp extends StatelessWidget {
  const InkyCalApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Inky Impressions Setup',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: Colors.indigo,
      ),
      home: const ProvisioningWizardScreen(),
    );
  }
}
