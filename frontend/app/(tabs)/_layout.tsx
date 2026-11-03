import { Redirect, Tabs } from "expo-router";
import { NativeTabs } from "expo-router/unstable-native-tabs";
// Bottom nav uses genuine solid/filled icons (pure SVG, no native font linking — safe in Expo Go
// and web). Lucide is outline-only by design; faking "solid" with thicker strokes looks wrong, so
// Lucide stays for secondary in-screen actions only (see other screens) and never the tab bar.
import { ChatBubbleLeftRight, Home, Megaphone, ShieldExclamation, BookOpen } from "@nandorojo/heroicons/24/solid";
import React, { useMemo } from "react";
import { Platform, Text, useWindowDimensions } from "react-native";

import { badgeText, countNeedingYou } from "@/src/domain/tabBadges";
import { useNewSevereAlertCount } from "@/src/higgins/scamAlertBadge";
import { useApollo } from "@/src/store/ApolloContext";
import { useAccountMonitorDueCheck } from "@/src/hooks/useAccountMonitorDueCheck";
import { fonts, useTheme } from "@/src/theme";

const isIOS26 = Platform.OS === "ios" && parseInt(String(Platform.Version), 10) >= 26;
const NAV_ICON_SIZE = 25;
const TAB_COUNT = 5;

// Tab order: Home → Threats → Ask Higgins → Alerts → Learn
// Hidden tabs (accessible via routes but not in the tab bar): guard, protection, settings
export default function TabsLayout() {
  const { colors } = useTheme();
  const { width: screenW, height: screenH } = useWindowDimensions();
  // Tablets (shortest side 600pt or more) have room for the longer tab names.
  const isTablet = Math.min(screenW, screenH) >= 600;
  const alertsTitle = isTablet ? "Scam Alerts" : "Alerts";
  const learnTitle = isTablet ? "Learn with Higgins" : "Learn";
  const { ready, setupDone, events, deviceId } = useApollo();
  // Tab counts: threats that still need the person, and new High/Extreme scam alerts they haven't seen.
  const needYou = useMemo(() => countNeedingYou(events), [events]);
  const newAlerts = useNewSevereAlertCount(deviceId);
  const threatsBadge = badgeText(needYou);
  const alertsBadge = badgeText(newAlerts);
  useAccountMonitorDueCheck();
  if (ready && !setupDone) return <Redirect href="/onboarding" />;

  if (isIOS26) {
    return (
      <NativeTabs>
        <NativeTabs.Trigger name="home"><NativeTabs.Trigger.Icon sf="house.fill" /><NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label></NativeTabs.Trigger>
        <NativeTabs.Trigger name="patrol"><NativeTabs.Trigger.Icon sf="exclamationmark.shield.fill" /><NativeTabs.Trigger.Label>Threats</NativeTabs.Trigger.Label>{threatsBadge ? <NativeTabs.Trigger.Badge>{threatsBadge}</NativeTabs.Trigger.Badge> : null}</NativeTabs.Trigger>
        <NativeTabs.Trigger name="ask"><NativeTabs.Trigger.Icon sf="bubble.left.fill" /><NativeTabs.Trigger.Label>Ask Higgins</NativeTabs.Trigger.Label></NativeTabs.Trigger>
        <NativeTabs.Trigger name="scams"><NativeTabs.Trigger.Icon sf="megaphone.fill" /><NativeTabs.Trigger.Label>{alertsTitle}</NativeTabs.Trigger.Label>{alertsBadge ? <NativeTabs.Trigger.Badge>{alertsBadge}</NativeTabs.Trigger.Badge> : null}</NativeTabs.Trigger>
        <NativeTabs.Trigger name="learn"><NativeTabs.Trigger.Icon sf="book.fill" /><NativeTabs.Trigger.Label>{learnTitle}</NativeTabs.Trigger.Label></NativeTabs.Trigger>
      </NativeTabs>
    );
  }

  // Icon and label use deliberately different golds when active (Brand Gold vs. Gold Highlight) —
  // the icon alone should already make the selected tab obvious; the label is a softer echo.
  const tabIcon = (Icon: React.ComponentType<{ color?: string; width?: number; height?: number }>) =>
    function TabIcon({ focused }: { focused: boolean }) { return <Icon color={focused ? colors.navActiveIcon : colors.navInactiveIcon} width={NAV_ICON_SIZE} height={NAV_ICON_SIZE} />; };
  // One line on every phone: the label never wraps. Its size follows the column width (a fifth of the bar,
  // less the tab's 5pt side padding; "Ask Higgins" is ~6 font-px per point at this weight), so it fits on
  // narrow phones too; a large system text size is capped for the same reason.
  const labelSize = Math.max(8, Math.min(11, (screenW / TAB_COUNT - 10) / 6.1));
  const badgeStyle = { backgroundColor: colors.barking, color: colors.onBrand, fontFamily: fonts.textSemibold, fontSize: 10 };
  const tabLabel = (title: string) =>
    function TabLabel({ focused }: { focused: boolean }) {
      return (
        <Text
          numberOfLines={1}
          adjustsFontSizeToFit
          minimumFontScale={0.75}
          maxFontSizeMultiplier={1.2}
          style={{ fontFamily: fonts.textSemibold, fontSize: labelSize, textAlign: "center", marginTop: 2, color: focused ? colors.navActiveLabel : colors.navInactiveLabel }}
        >
          {title}
        </Text>
      );
    };

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: colors.navyDeep, borderTopWidth: 0,
          shadowColor: "#000000", shadowOpacity: 0.22, shadowRadius: 10, shadowOffset: { width: 0, height: -3 }, elevation: 12,
          ...(Platform.OS === "web" ? { height: 64 } : {}),
        },
        // Five equal columns, so the items sit evenly spaced across every screen width.
        tabBarItemStyle: { alignSelf: "center" },
        sceneStyle: { backgroundColor: colors.surface },
      }}
    >
      <Tabs.Screen name="home" options={{ title: "Home", tabBarButtonTestID: "tab-home", tabBarIcon: tabIcon(Home), tabBarLabel: tabLabel("Home") }} />
      <Tabs.Screen name="patrol" options={{ title: "Threats", tabBarButtonTestID: "tab-threats", tabBarIcon: tabIcon(ShieldExclamation), tabBarLabel: tabLabel("Threats"), tabBarBadge: threatsBadge, tabBarBadgeStyle: badgeStyle, tabBarAccessibilityLabel: needYou ? `Threats, ${needYou} need you` : "Threats" }} />
      <Tabs.Screen name="ask" options={{ title: "Ask Higgins", tabBarButtonTestID: "tab-ask", tabBarIcon: tabIcon(ChatBubbleLeftRight), tabBarLabel: tabLabel("Ask Higgins") }} />
      <Tabs.Screen name="scams" options={{ title: alertsTitle, tabBarButtonTestID: "tab-scams", tabBarIcon: tabIcon(Megaphone), tabBarLabel: tabLabel(alertsTitle), tabBarBadge: alertsBadge, tabBarBadgeStyle: badgeStyle, tabBarAccessibilityLabel: newAlerts ? `${alertsTitle}, ${newAlerts} new serious alerts` : alertsTitle }} />
      <Tabs.Screen name="learn" options={{ title: learnTitle, tabBarButtonTestID: "tab-learn", tabBarIcon: tabIcon(BookOpen), tabBarLabel: tabLabel(learnTitle) }} />
      {/* Hidden tabs — still routable for deep links and backwards compatibility */}
      <Tabs.Screen name="guard" options={{ href: null }} />
      <Tabs.Screen name="protection" options={{ href: null }} />
      <Tabs.Screen name="settings" options={{ href: null }} />
    </Tabs>
  );
}
