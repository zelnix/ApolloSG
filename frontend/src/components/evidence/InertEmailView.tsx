// The Original Email viewer on a phone: the inert document from domain/inertEmail.ts in a locked-down web view.
// No JavaScript, no storage, no cookies, no files, no new windows, no link previews, no phone/address detection, and
// every navigation refused — including ones the web view would otherwise hand to another app. The document itself
// carries no destinations and a policy that blocks every network request.
import React, { useMemo, useState } from "react";
import { ScrollView, Text, View, type StyleProp, type ViewStyle } from "react-native";
import { WebView } from "react-native-webview";

import { fittedEmail, type InertEmail } from "@/src/domain/inertEmail";

/** Only the document itself may load; anything else (a link, a redirect, an app address) is refused, never opened. */
const onlyTheDocument = (request: { url: string }) => /^about:(blank|srcdoc)$/i.test(request.url);

// This limits only the rendered copy crossing the native bridge, never the retained source.
const MAX_PREVIEW_CHARACTERS = 1024 * 1024;

export function InertEmailView({ email, fallbackText, style, testID }: { email: InertEmail; fallbackText?: string | null; style?: StyleProp<ViewStyle>; testID?: string }) {
  const [width, setWidth] = useState(0);
  const [failedDocument, setFailedDocument] = useState<string | null>(null);
  const unavailable = failedDocument === email.document || email.document.length > MAX_PREVIEW_CHARACTERS;
  const source = useMemo(() => unavailable ? null : { html: fittedEmail(email, width) }, [email, width, unavailable]);
  const failed = () => {
    // No source text, HTML or addresses enter diagnostics. Do not automatically restart a failed renderer.
    console.warn("[EmailEvidence] formatted preview renderer unavailable");
    setFailedDocument(email.document);
  };
  return (
    <View style={[{ overflow: "hidden", backgroundColor: "#FFFFFF" }, style]} testID={testID} onLayout={(e) => setWidth(Math.round(e.nativeEvent.layout.width))}>
      {unavailable ? (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 12 }} testID={testID ? `${testID}-fallback` : undefined}>
          <Text style={{ color: "#5A6472", marginBottom: 12 }}>The formatted preview could not be displayed. {fallbackText ? "Showing the captured text instead." : "No captured text is available to display."} The original email is unchanged.</Text>
          {fallbackText ? <Text selectable style={{ color: "#000000", fontSize: 14, lineHeight: 21 }}>{fallbackText}</Text> : null}
        </ScrollView>
      ) : width && source ? (
        <WebView
          source={source}
          originWhitelist={["*"]}
          onShouldStartLoadWithRequest={onlyTheDocument}
          javaScriptEnabled={false}
          javaScriptCanOpenWindowsAutomatically={false}
          setSupportMultipleWindows={false}
          domStorageEnabled={false}
          cacheEnabled={false}
          incognito
          thirdPartyCookiesEnabled={false}
          sharedCookiesEnabled={false}
          allowFileAccess={false}
          allowFileAccessFromFileURLs={false}
          allowUniversalAccessFromFileURLs={false}
          mixedContentMode="never"
          geolocationEnabled={false}
          mediaPlaybackRequiresUserAction
          allowsInlineMediaPlayback={false}
          allowsLinkPreview={false}
          allowsBackForwardNavigationGestures={false}
          dataDetectorTypes="none"
          // Static email content does not need Android's GPU compositor during tab/modal transitions.
          androidLayerType="software"
          onError={failed}
          onRenderProcessGone={failed}
          onContentProcessDidTerminate={failed}
          textZoom={100}
          nestedScrollEnabled
          style={{ backgroundColor: "#FFFFFF" }}
        />
      ) : null}
    </View>
  );
}
