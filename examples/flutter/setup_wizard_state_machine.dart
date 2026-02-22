/// Setup wizard state machine for InkyCal BLE provisioning.
///
/// This file is framework-agnostic and can be used with Riverpod/BLoC.
enum SetupStep {
  scan,
  pair,
  wifi,
  googleAuth,
  icloud,
  settings,
  apply,
  done,
  error,
}

class SetupState {
  final SetupStep step;
  final String? message;
  final bool busy;

  const SetupState({required this.step, this.message, this.busy = false});

  SetupState copyWith({SetupStep? step, String? message, bool? busy}) {
    return SetupState(
      step: step ?? this.step,
      message: message ?? this.message,
      busy: busy ?? this.busy,
    );
  }
}

class SetupWizardController {
  SetupState state = const SetupState(step: SetupStep.scan);

  void onDeviceConnected() {
    state = state.copyWith(step: SetupStep.pair, busy: false);
  }

  void onPairingConfirmed() {
    state = state.copyWith(step: SetupStep.wifi);
  }

  Future<void> submitWifi(String ssid, String password) async {
    state = state.copyWith(busy: true, message: 'Connecting Wi-Fi...');
    // TODO: write BLE Wi-Fi characteristic.
    state = state.copyWith(step: SetupStep.googleAuth, busy: false);
  }

  Future<void> completeGoogleAuth(String oauthCode) async {
    state = state.copyWith(busy: true, message: 'Saving Google token...');
    // TODO: write BLE OAuth code characteristic.
    state = state.copyWith(step: SetupStep.icloud, busy: false);
  }

  Future<void> submitIcloud(String username, String appPassword) async {
    state = state.copyWith(busy: true, message: 'Validating iCloud...');
    // TODO: write BLE iCloud characteristic.
    state = state.copyWith(step: SetupStep.settings, busy: false);
  }

  Future<void> submitSettings(Map<String, dynamic> settings) async {
    state = state.copyWith(busy: true, message: 'Applying settings...');
    // TODO: write BLE settings characteristic.
    state = state.copyWith(step: SetupStep.apply, busy: false);
  }

  Future<void> applyAndRestart() async {
    state = state.copyWith(busy: true, message: 'Restarting InkyCal...');
    // TODO: write BLE apply characteristic.
    state = state.copyWith(step: SetupStep.done, busy: false, message: 'Complete');
  }

  void fail(String error) {
    state = state.copyWith(step: SetupStep.error, busy: false, message: error);
  }
}
