// The Original Email viewer in a browser: the inert document from domain/inertEmail.ts in a fully sandboxed frame —
// no scripts, forms, pop-ups, downloads or navigation of this page, and no shared origin. The document itself carries
// no destinations and a policy that blocks every network request.
import React, { useState } from "react";
import { View, type StyleProp, type ViewStyle } from "react-native";

import { fittedEmail, type InertEmail } from "@/src/domain/inertEmail";

export function InertEmailView({ email, style, testID }: { email: InertEmail; fallbackText?: string | null; style?: StyleProp<ViewStyle>; testID?: string }) {
  const [width, setWidth] = useState(0);
  return (
    <View style={[{ overflow: "hidden", backgroundColor: "#FFFFFF" }, style]} testID={testID} onLayout={(e) => setWidth(Math.round(e.nativeEvent.layout.width))}>
      {width ? React.createElement("iframe", {
        srcDoc: fittedEmail(email, width), sandbox: "", referrerPolicy: "no-referrer", title: "Original email", tabIndex: -1,
        style: { border: 0, width: "100%", height: "100%", display: "block", backgroundColor: "#FFFFFF" },
      }) : null}
    </View>
  );
}
